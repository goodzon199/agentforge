from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.client import llm_client
from app.models import (
    AgentAction,
    Conversation,
    ConversationMessage,
    Order,
    PartRequest,
    Quote,
    SupplierSearchAttempt,
    Task,
)
from app.models.enums import QuoteStatus, SupplierAttemptStatus, TaskStatus
from app.reliability.circuit_breaker import breaker_registry
from app.reliability.errors import from_llm_status

# Stages of the customer pipeline and their target SLA (seconds). Sourced from
# settings so operators can tune them without code changes.
_PIPELINE_OBJECTIVES = (
    "process_customer_message",
    "search_parts",
    "pricing_parts",
    "sales_draft",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(0.95 * (len(ordered) - 1))
    return round(ordered[idx], 2)


def _fmt_money(value: Decimal | None) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(value):.2f}"


class AnalyticsService:
    """Pilot analytics: business numbers + operational metrics (sprint 3.1).

    Everything is derived from existing entities (conversations, quotes,
    orders, tasks, search attempts, audit trail) — no new storage.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def pilot(self, *, company_id: uuid.UUID, days: int = 1) -> dict[str, Any]:
        since = _now() - timedelta(days=max(1, days))

        conversations = self._rows(
            Conversation, Conversation.created_at >= since
        )
        conversation_ids = {str(c.id) for c in conversations}

        messages = self._rows(
            ConversationMessage,
            ConversationMessage.created_at >= since,
        )
        customer_messages = [m for m in messages if m.sender_type == "customer"]

        # Conversations the AI actually responded to (>=1 agent message).
        agent_reply_conv_ids = {
            str(m.conversation_id) for m in messages if m.sender_type == "agent"
        }

        takeover_rows = self._rows(
            AgentAction,
            (AgentAction.created_at >= since)
            & (AgentAction.action_type == "conversation_takeover"),
        )
        handed_over = {str(a.target_id) for a in takeover_rows}

        quotes = self._rows(Quote, Quote.created_at >= since)
        sent_states = {
            QuoteStatus.sent,
            QuoteStatus.accepted,
            QuoteStatus.rejected,
            QuoteStatus.expired,
            QuoteStatus.converted_to_order,
        }
        accepted_states = {QuoteStatus.accepted, QuoteStatus.converted_to_order}
        quotes_sent = [q for q in quotes if q.status in sent_states]
        quotes_accepted = [q for q in quotes if q.status in accepted_states]

        orders = self._rows(Order, Order.created_at >= since)
        revenue, gross_profit = self._money(orders)

        return {
            "period_days": days,
            "requests_total": len(customer_messages),
            "conversations_total": len(conversations),
            "ai_handled": len(conversation_ids & agent_reply_conv_ids),
            "handed_to_manager": len(conversation_ids & handed_over),
            "takeover_rate": round(
                len(conversation_ids & handed_over) / len(conversations) * 100
                if conversations
                else 0.0,
                1,
            ),
            "part_requests_total": len(self._rows(PartRequest, PartRequest.created_at >= since)),
            "quotes_sent": len(quotes_sent),
            "quotes_accepted": len(quotes_accepted),
            "orders_total": len(orders),
            "revenue": _fmt_money(revenue),
            "gross_profit": _fmt_money(gross_profit),
            "avg_response_seconds": self._avg_response_seconds(customer_messages),
            "pipeline": self._pipeline(since),
            "suppliers": self._supplier_stats(since),
            "llm": {
                "calls": llm_client.stats["calls"],
                "failures": llm_client.stats["failures"],
                "failure_rate": round(
                    llm_client.stats["failures"] / llm_client.stats["calls"] * 100
                    if llm_client.stats["calls"]
                    else 0.0,
                    1,
                ),
                "available": llm_client.available,
            },
            "task_timeouts": self._task_timeouts(since),
            "reliability": self._reliability(since),
        }

    # --- Internals ---------------------------------------------------------

    def _rows(self, model, *conditions):
        stmt = select(model).where(*conditions)
        return list(self.db.scalars(stmt).unique().all())

    def _money(self, orders: list[Order]) -> tuple[Decimal, Decimal]:
        revenue = Decimal("0")
        profit = Decimal("0")
        for order in orders:
            if order.status == "cancelled" or order.order_total is None:
                continue
            revenue += order.order_total
            for item in order.items or []:
                total = self._dec(item.get("total_price"))
                margin = self._dec(item.get("margin_percent"))
                if total and margin is not None:
                    profit += total * margin / (Decimal("100") + margin)
        return revenue, profit

    @staticmethod
    def _dec(value) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    def _avg_response_seconds(
        self, customer_messages: list[ConversationMessage]
    ) -> float | None:
        """Average time from the customer's message to the first agent reply.

        The comparison is done in Python: SQLite's ``func.now()`` stores
        second-precision timestamps while SQLAlchemy binds full microsecond
        datetimes, so an ``ORDER BY ... first agent reply >= message`` query
        string-compares and never matches. Loading the replies and comparing
        the parsed datetime objects is exact regardless.
        """
        deltas: list[float] = []
        conv_ids = {m.conversation_id for m in customer_messages}
        replies_by_conv: dict[uuid.UUID, list[ConversationMessage]] = {}
        if conv_ids:
            stmt = (
                select(ConversationMessage)
                .where(ConversationMessage.sender_type == "agent")
                .where(ConversationMessage.conversation_id.in_(conv_ids))
                .order_by(ConversationMessage.created_at.asc())
            )
            for m in self.db.scalars(stmt).unique().all():
                replies_by_conv.setdefault(m.conversation_id, []).append(m)
        for message in customer_messages:
            first_reply = next(
                (
                    r
                    for r in replies_by_conv.get(message.conversation_id, [])
                    if r.created_at >= message.created_at
                ),
                None,
            )
            if first_reply is None:
                continue
            delta = (first_reply.created_at - message.created_at).total_seconds()
            if delta >= 0:
                deltas.append(delta)
        if not deltas:
            return None
        return round(median(deltas), 1)

    def _pipeline(self, since: datetime) -> list[dict[str, Any]]:
        from app.core.config import settings

        sla = settings.pipeline_sla_seconds
        result: list[dict[str, Any]] = []
        for objective in _PIPELINE_OBJECTIVES:
            stmt = (
                select(Task)
                .where(Task.objective == objective)
                .where(Task.started_at.isnot(None))
                .where(Task.completed_at.isnot(None))
                .where(Task.started_at >= since)
            )
            tasks = list(self.db.scalars(stmt).unique().all())
            durations = [
                (t.completed_at - t.started_at).total_seconds() for t in tasks
            ]
            sla_seconds = sla.get(objective, 5.0)
            on_sla = sum(1 for d in durations if d <= sla_seconds)
            failed = sum(1 for t in tasks if t.status == TaskStatus.failed)
            result.append(
                {
                    "objective": objective,
                    "count": len(tasks),
                    "failed": failed,
                    "avg_seconds": round(sum(durations) / len(durations), 2)
                    if durations
                    else None,
                    "p95_seconds": _p95(durations),
                    "sla_seconds": sla_seconds,
                    "on_sla_pct": round(on_sla / len(tasks) * 100, 1)
                    if tasks
                    else None,
                }
            )
        return result

    def _supplier_stats(self, since: datetime) -> dict[str, Any]:
        stmt = (
            select(SupplierSearchAttempt)
            .where(SupplierSearchAttempt.created_at >= since)
            .where(SupplierSearchAttempt.status != SupplierAttemptStatus.pending)
        )
        attempts = list(self.db.scalars(stmt).unique().all())
        failed = [a for a in attempts if a.status == SupplierAttemptStatus.failed]
        latencies = [a.latency_ms for a in attempts if a.latency_ms is not None]
        return {
            "attempts_total": len(attempts),
            "attempts_failed": len(failed),
            "failure_rate": round(len(failed) / len(attempts) * 100, 1)
            if attempts
            else 0.0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1)
            if latencies
            else None,
            "p95_latency_ms": _p95([float(v) for v in latencies]) if latencies else None,
        }

    def _task_timeouts(self, since: datetime) -> int:
        stmt = (
            select(Task)
            .where(Task.status == TaskStatus.failed)
            .where(Task.error.contains("task_timeout"))
            .where(Task.started_at >= since)
        )
        return len(list(self.db.scalars(stmt).unique().all()))

    def _reliability(self, since: datetime) -> dict[str, Any]:
        """Reliability layer (sprint 3.5): breaker states, DLQ, failure kinds.

        Failure kinds are aggregated from the canonical codes persisted on
        LLMUsage.status and DeadTask.exception_kind, so agents and the
        dashboard speak the same language (timeout / unavailable / rate_limited
        / authentication / permission_denied / invalid_response /
        supplier_error / internal_error).
        """
        from app.models import DeadTask, LLMUsage

        llm_statuses = [
            u.status
            for u in self._rows(LLMUsage, LLMUsage.created_at >= since)
            if u.status != "ok"
        ]
        dead = self._rows(DeadTask, DeadTask.created_at >= since)
        kinds: dict[str, int] = {}
        for status in llm_statuses:
            code = from_llm_status(status).value
            if code != "ok":
                kinds[code] = kinds.get(code, 0) + 1
        for entry in dead:
            kinds[entry.exception_kind] = kinds.get(entry.exception_kind, 0) + 1

        replays = len(
            self._rows(
                Task,
                Task.replayed_from_task_id.isnot(None),
                Task.created_at >= since,
            )
        )
        return {
            "breakers": breaker_registry.snapshots(),
            "dead_tasks": len(dead),
            "replays": replays,
            "failures_by_kind": kinds,
        }
