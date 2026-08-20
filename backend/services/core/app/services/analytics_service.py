from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.client import llm_client
from app.models import (
    AgentAction,
    AgentFeedback,
    Conversation,
    ConversationMessage,
    Task,
)
from app.models.enums import AgentFeedbackType, TaskStatus
from app.reliability.circuit_breaker import breaker_registry
from app.reliability.errors import from_llm_status

# Stages of the customer pipeline and their target SLA (seconds). Sourced from
# settings so operators can tune them without code changes. Sprint 5.0: the
# automotive funnel stages (search/pricing/sales) belong to the autoparts
# service; core keeps the platform entry stage and measures whatever task
# objectives exist in the current deployment.
_PIPELINE_OBJECTIVES = (
    "process_customer_message",
)


def _now() -> datetime:
    return datetime.now(UTC)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(0.95 * (len(ordered) - 1))
    return round(ordered[idx], 2)


class AnalyticsService:
    """Pilot analytics (platform scope, sprint 3.1 + sprint 5.0).

    Everything is derived from platform entities (conversations, messages,
    tasks, actions, audit trail) — no new storage. Automotive domain metrics
    (quotes, orders, suppliers, funnel accuracy) are computed by the
    autoparts service over its internal endpoint.
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

        response = self._response_times(customer_messages)

        packs = self._pack_metrics()

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
            "avg_response_seconds": response["avg"],
            "p95_response_seconds": response["p95"],
            "pipeline": self._pipeline(since),
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
            "assist": self._assist(company_id, since),
            "packs": packs,
            **self._aggregate_pack_business(packs),
        }

    # --- Pack metrics (sprint 5.8.2) ---------------------------------------

    def _pack_metrics(self) -> list[dict[str, Any]]:
        """Fetch each active pack's ``/internal/metrics``.

        A pack that is registered but unreachable is reported as
        ``{"status": "unavailable"}`` — never ``None`` — so the dashboard can
        distinguish "no data yet" from "pack is down".
        """
        from shared.internal import internal_get

        from app.models import Pack

        packs = self.db.scalars(
            select(Pack).where(Pack.is_active.is_(True))
        ).unique().all()
        result: list[dict[str, Any]] = []
        for pack in packs:
            try:
                data = internal_get(pack.base_url, "/internal/metrics", timeout=5.0)
            except Exception:
                result.append({"namespace": pack.name, "status": "unavailable"})
                continue
            result.append(
                {
                    "namespace": data.get("namespace", pack.name),
                    "status": "ok",
                    "metrics": data.get("metrics", {}),
                }
            )
        return result

    @staticmethod
    def _aggregate_pack_business(
        packs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Roll up business numbers from the pack metric contract.

        Only packs that answered with metrics contribute; an unavailable pack
        contributes nothing (its own entry still carries the status).
        """
        revenue = 0.0
        orders_total = 0
        quotes_sent = 0
        part_requests_total = 0
        attempts_total = 0
        success_weighted = 0.0
        for entry in packs:
            if entry.get("status") != "ok":
                continue
            metrics = entry.get("metrics") or {}
            revenue += float(metrics.get("revenue") or 0)
            orders_total += int(metrics.get("orders") or 0)
            quotes_sent += int(metrics.get("quotes_sent") or 0)
            part_requests_total += int(metrics.get("part_requests_total") or 0)
            suppliers = metrics.get("suppliers") or {}
            attempts = int(suppliers.get("attempts_total") or 0)
            attempts_total += attempts
            success_weighted += attempts * float(suppliers.get("success_rate") or 0)
        success_rate = (
            round(success_weighted / attempts_total, 1) if attempts_total else None
        )
        return {
            "revenue": f"{revenue:.2f}",
            "gross_profit": None,
            "orders_total": orders_total,
            "quotes_sent": quotes_sent,
            "part_requests_total": part_requests_total,
            "suppliers": {
                "attempts_total": attempts_total,
                "attempts_failed": (
                    round(attempts_total * (100 - success_rate) / 100)
                    if success_rate is not None
                    else 0
                ),
                "failure_rate": (
                    round(100 - success_rate, 1)
                    if success_rate is not None
                    else None
                ),
                "avg_latency_ms": None,
                "p95_latency_ms": None,
            },
        }

    # --- Internals ---------------------------------------------------------

    def _assist(self, company_id: uuid.UUID, since: datetime) -> dict[str, Any]:
        """Sprint 3.8.2: manager edit rate + auto-send counts.

        Auto-send decisions are persisted on the platform ``AgentAction``
        result payload, so this stays computable in core.
        """
        feedback = self._rows(
            AgentFeedback,
            AgentFeedback.company_id == company_id,
            AgentFeedback.created_at >= since,
        )
        unchanged = sum(
            1 for fb in feedback if fb.feedback_type == AgentFeedbackType.approved_unchanged
        )
        edited = sum(1 for fb in feedback if fb.feedback_type == AgentFeedbackType.approved_edited)
        total = unchanged + edited

        auto_sends = self._auto_sends(company_id, since)
        return {
            "sends_total": total,
            "sends_unchanged": unchanged,
            "sends_edited": edited,
            "manager_edit_rate": round(unchanged / total * 100, 1) if total else None,
            "auto_sends": auto_sends,
        }

    def _auto_sends(self, company_id: uuid.UUID, since: datetime) -> int:
        """How many sends went out without a human (Controlled Auto, 3.8.3).

        The send action carries ``result_data["auto_send"]["auto"]`` when it
        was auto-sent; anything else went through manager approval.
        """
        stmt = (
            select(AgentAction)
            .where(AgentAction.company_id == company_id)
            .where(AgentAction.action_type == "send_customer_message")
            .where(AgentAction.created_at >= since)
        )
        count = 0
        for action in self.db.scalars(stmt).unique().all():
            result = action.result_data or {}
            if (result.get("auto_send") or {}).get("auto") is True:
                count += 1
        return count

    def _rows(self, model, *conditions):
        stmt = select(model).where(*conditions)
        return list(self.db.scalars(stmt).unique().all())

    def _response_times(
        self, customer_messages: list[ConversationMessage]
    ) -> dict[str, float | None]:
        """Avg and P95 time from the customer's message to the first agent reply.

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
            return {"avg": None, "p95": None}
        return {
            "avg": round(sum(deltas) / len(deltas), 1),
            "p95": _p95(deltas),
        }

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
