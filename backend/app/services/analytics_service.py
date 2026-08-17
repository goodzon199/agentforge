from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.client import llm_client
from app.models import (
    AgentAction,
    AgentFeedback,
    Conversation,
    ConversationMessage,
    Order,
    PartRequest,
    Quote,
    SupplierSearchAttempt,
    SupplierSearchRun,
    Task,
)
from app.models.enums import (
    AgentFeedbackType,
    QuoteStatus,
    SupplierAttemptStatus,
    SupplierSearchStatus,
    TaskStatus,
)
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
    return datetime.now(UTC)


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

        part_requests = self._rows(PartRequest, PartRequest.created_at >= since)
        orders = self._rows(Order, Order.created_at >= since)
        revenue, gross_profit = self._money(orders)

        response = self._response_times(customer_messages)

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
            "part_requests_total": len(part_requests),
            "quotes_sent": len(quotes_sent),
            "quotes_accepted": len(quotes_accepted),
            "orders_total": len(orders),
            "revenue": _fmt_money(revenue),
            "gross_profit": _fmt_money(gross_profit),
            "avg_response_seconds": response["avg"],
            "p95_response_seconds": response["p95"],
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
            "assist": self._assist(company_id, since),
            "sprint39": self._sprint39(
                since,
                conversations=conversations,
                conversation_ids=conversation_ids,
                handed_over=handed_over,
                customer_messages=customer_messages,
                part_requests=part_requests,
                quotes=quotes,
                quotes_sent=quotes_sent,
                quotes_accepted=quotes_accepted,
                orders=orders,
                revenue=revenue,
                gross_profit=gross_profit,
                response=response,
                company_id=company_id,
            ),
        }

    # --- Internals ---------------------------------------------------------

    def _sprint39(
        self,
        since: datetime,
        *,
        conversations: list[Conversation],
        conversation_ids: set[str],
        handed_over: set[str],
        customer_messages: list[ConversationMessage],
        part_requests: list[PartRequest],
        quotes: list[Quote],
        quotes_sent: list[Quote],
        quotes_accepted: list[Quote],
        orders: list[Order],
        revenue: Decimal,
        gross_profit: Decimal,
        response: dict[str, float | None],
        company_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Sprint 3.9 — the full Pilot-500 scoreboard.

        One flat table of the metrics the pilot is judged on, so operators can
        see after N real requests exactly where the system stands: funnel
        accuracy, the human loop (manager unchanged / edited / rejected),
        Controlled Auto (eligible / sent / error), money, cost and automation.
        """
        from app.core.config import settings

        requests_total = len(customer_messages)
        part_requests_total = len(part_requests)
        quotes_total = len(quotes)

        # --- Funnel accuracy ---------------------------------------------
        # Intake: how often the AI structured a request fully (no missing
        # fields) — i.e. got enough to search without asking again.
        ready_prs = [pr for pr in part_requests if not pr.missing_fields]
        # Fitment: for VIN/vehicle requests, was compatibility confirmed.
        # The confidence comes from the Fitment Engine snapshot (sprint 4.0) —
        # never from the intent confidence. Requests without a vehicle
        # (article-only) are "N/A" — they have nothing to fit.
        from app.core.policies import DEFAULT_SALES_POLICY

        fitment_threshold = DEFAULT_SALES_POLICY["auto_send_min_fitment_confidence"]
        vehicle_dependent = [
            pr
            for pr in part_requests
            if pr.vehicle_id or (pr.structured_data or {}).get("vehicle")
        ]
        fitment_ok = [
            pr
            for pr in vehicle_dependent
            if (pr.structured_data or {}).get("fitment", {}).get("confidence") is not None
            and (pr.structured_data or {}).get("fitment", {}).get("confidence") >= fitment_threshold
        ]
        # Search: completed search runs that actually found offers.
        runs = self._rows(SupplierSearchRun, SupplierSearchRun.created_at >= since)
        completed_runs = [
            r for r in runs if r.status == SupplierSearchStatus.completed
        ]
        runs_with_offers = [r for r in completed_runs if r.offers_found > 0]

        # --- Manager loop -------------------------------------------------
        feedback = self._rows(
            AgentFeedback,
            AgentFeedback.company_id == company_id,
            AgentFeedback.created_at >= since,
        )
        sends_unchanged = sum(
            1 for fb in feedback if fb.feedback_type == AgentFeedbackType.approved_unchanged
        )
        sends_edited = sum(1 for fb in feedback if fb.feedback_type == AgentFeedbackType.approved_edited)
        sends_rejected = sum(1 for fb in feedback if fb.feedback_type == AgentFeedbackType.rejected)
        sends_total = sends_unchanged + sends_edited + sends_rejected

        # --- Controlled Auto ---------------------------------------------
        eligible, auto_sent_count, auto_send_outcomes = self._auto_stats(
            quotes_sent, since
        )
        auto_sent_quotes = [q for q in quotes_sent if q.auto_sent]
        # Auto-send error: an auto-sent quote that afterwards was rejected by
        # the customer / expired, got a negative correction, or the human took
        # over the conversation. This is the "trust signal" — it must approach
        # zero before widening the AUTO zone.
        error_quotes = [
            q
            for q in auto_sent_quotes
            if q.status in (QuoteStatus.rejected, QuoteStatus.expired)
        ]
        negative_types = {
            AgentFeedbackType.incorrect_fact,
            AgentFeedbackType.wrong_recommendation,
            AgentFeedbackType.bad_tone,
        }
        negative_fb_ids = {
            fb.action_id
            for fb in feedback
            if fb.feedback_type in negative_types
        }
        for q in auto_sent_quotes:
            if q.id in auto_send_outcomes and auto_send_outcomes[q.id] in negative_fb_ids:
                error_quotes.append(q)

        # --- Money & cost ------------------------------------------------
        llm_cost = Decimal("0")
        from app.models import LLMUsage

        for usage in self._rows(LLMUsage, LLMUsage.created_at >= since):
            llm_cost += Decimal(str(usage.estimated_cost_rub))
        infra_per = Decimal(str(settings.infra_cost_per_request_rub))
        llm_per = llm_cost / requests_total if requests_total else Decimal("0")

        # --- Automation --------------------------------------------------
        manager_send_convs = self._manager_send_conversations()
        full_automation_convs = {
            cid
            for cid in conversation_ids
            if cid not in handed_over and cid not in manager_send_convs
        }

        def _pct(numerator: int, denominator: int) -> float | None:
            return round(numerator / denominator * 100, 1) if denominator else None

        return {
            "target_requests": settings.pilot_target_requests,
            "real_requests": requests_total,
            "remaining_to_target": max(0, settings.pilot_target_requests - requests_total),
            "intake_accuracy": _pct(len(ready_prs), part_requests_total),
            "search_success": _pct(len(runs_with_offers), len(completed_runs)),
            "correct_fitment": _pct(len(fitment_ok), len(vehicle_dependent)),
            "quotes_generated": _pct(quotes_total, part_requests_total),
            "quote_guard_pass": _pct(
                sum(1 for q in quotes if q.guard_status == "pass"), quotes_total
            ),
            "manager_unchanged_send": _pct(sends_unchanged, sends_total),
            "manager_edited": _pct(sends_edited, sends_total),
            "manager_rejected": _pct(sends_rejected, sends_total),
            "manager_sends_total": sends_total,
            "controlled_auto_eligible": _pct(eligible, len(quotes_sent)),
            "controlled_auto_sent": _pct(auto_sent_count, eligible),
            "auto_send_error_rate": _pct(len(error_quotes), auto_sent_count),
            "avg_response_seconds": response["avg"],
            "p95_response_seconds": response["p95"],
            "quote_to_accepted": _pct(len(quotes_accepted), len(quotes_sent)),
            "accepted_to_order": _pct(len(orders), len(quotes_accepted)),
            "revenue": _fmt_money(revenue),
            "gross_profit": _fmt_money(gross_profit),
            "llm_cost_per_request": f"{llm_per:.2f}",
            "infra_cost_per_request": f"{infra_per:.2f}",
            "total_cost_per_request": f"{llm_per + infra_per:.2f}",
            "human_takeover": _pct(
                len(conversation_ids & handed_over), len(conversations)
            ),
            "full_automation": _pct(len(full_automation_convs), len(conversations)),
        }

    def _manager_send_conversations(self) -> set[str]:
        """Conversation ids where a quote was delivered by a human.

        A human-sent quote is an executed ``send_customer_message`` action
        whose quote is NOT marked ``auto_sent`` (the auto path always sets it
        and records the decision snapshot). Computed once per report — not per
        conversation — so the pilot table stays cheap even at 500+ requests.
        """
        from app.models import Quote as QuoteModel

        stmt = (
            select(AgentAction)
            .where(AgentAction.action_type == "send_customer_message")
            .where(AgentAction.target_type == "quote")
            .where(AgentAction.status == "executed")
        )
        quote_ids = [uuid.UUID(a.target_id) for a in self.db.scalars(stmt).unique().all() if a.target_id]
        if not quote_ids:
            return set()
        conversations: set[str] = set()
        for quote in self.db.scalars(
            select(QuoteModel)
            .where(QuoteModel.id.in_(quote_ids))
            .where(QuoteModel.auto_sent.is_(False))
        ).unique().all():
            if quote.conversation_id is not None:
                conversations.add(str(quote.conversation_id))
        return conversations

    def _auto_stats(
        self, quotes_sent: list[Quote], since: datetime
    ) -> tuple[int, int, dict[uuid.UUID, uuid.UUID | None]]:
        """Controlled Auto numbers for the sent quotes in the window.

        Eligible = a sent quote whose auto-send decision (recomputed against
        the CURRENT policy, deterministically) has all checks green. Actually
        sent = it carries the persisted auto_send decision. Returns
        (eligible, auto_sent, action_id_by_quote) where the action ids let the
        caller detect negative feedback on auto-sends.
        """
        from app.services.auto_send_service import AutoSendService

        auto = AutoSendService(self.db)
        eligible = 0
        auto_sent = 0
        outcomes: dict[uuid.UUID, uuid.UUID | None] = {}
        for quote in quotes_sent:
            try:
                decision = auto.decision(quote)
            except Exception:
                continue
            if decision["auto"]:
                eligible += 1
            if quote.auto_send_decision is not None:
                auto_sent += 1
            if quote.auto_send_decision is not None:
                stmt = (
                    select(AgentAction)
                    .where(AgentAction.action_type == "send_customer_message")
                    .where(AgentAction.target_type == "quote")
                    .where(AgentAction.target_id == str(quote.id))
                    .where(AgentAction.status == "executed")
                )
                action = self.db.scalars(stmt).unique().first()
                outcomes[quote.id] = action.id if action is not None else None
        return eligible, auto_sent, outcomes

    def _assist(self, company_id: uuid.UUID, since: datetime) -> dict[str, Any]:
        """Sprint 3.8.2: manager edit rate + Controlled Auto sends."""
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
        """How many quotes went out without a human (Controlled Auto, 3.8.3).

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
