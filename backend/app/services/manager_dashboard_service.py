from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select

from app.models import (
    AgentFeedback,
    ApprovalRequest,
    Conversation,
    ConversationMessage,
    Customer,
    Order,
    PartRequest,
    Quote,
    SupplierSearchAttempt,
    SupplierSearchRun,
)
from app.models.enums import (
    AgentFeedbackType,
    ConversationMode,
    PartRequestStatus,
    QuoteStatus,
    SupplierAttemptStatus,
    SupplierSearchStatus,
)

# Part requests that are still in play (not finished / cancelled).
_ACTIVE_PR_STATUSES = {
    PartRequestStatus.collecting_data,
    PartRequestStatus.ready_for_search,
    PartRequestStatus.searching,
    PartRequestStatus.quoted,
}

_TERMINAL_QUOTE_STATUSES = {
    QuoteStatus.sent,
    QuoteStatus.accepted,
    QuoteStatus.rejected,
    QuoteStatus.expired,
    QuoteStatus.converted_to_order,
}

# A part request is "selection ready" while these hold.
_SELECTION_READY_PR_STATUSES = {
    PartRequestStatus.ready_for_search,
    PartRequestStatus.searching,
    PartRequestStatus.quoted,
}


def _day_start() -> datetime:
    now = datetime.now(UTC)
    return datetime.combine(now.date(), time.min, tzinfo=UTC)


class ManagerDashboardService:
    """Answers the three manager questions on the main screen (sprint 3.8):

    1. Where is a human needed right now?  (attention)
    2. What has AI already done today?      (today)
    3. What must be done right now?         (queue)
    """

    def __init__(self, db) -> None:
        self.db = db

    def dashboard(self, company_id: uuid.UUID) -> dict[str, Any]:
        return {
            "attention": self.attention(company_id),
            "today": self.today(company_id),
            "queue": self.queue(company_id),
            "shadow": self._shadow_stats(company_id),
            "assist": self.assist(company_id),
        }

    # --- 1. Where a human is needed ----------------------------------------

    def attention(self, company_id: uuid.UUID) -> dict[str, int]:
        return {
            "client_waiting_reply": self._client_waiting_reply(company_id),
            "approval_pending": self._approval_pending(company_id),
            "ai_unsure": self._ai_unsure(company_id),
            "supplier_error": self._supplier_error(company_id),
        }

    def _client_waiting_reply(self, company_id: uuid.UUID) -> int:
        last_sender = (
            select(ConversationMessage.sender_type)
            .where(ConversationMessage.conversation_id == Conversation.id)
            .order_by(
                ConversationMessage.created_at.desc(), ConversationMessage.id.desc()
            )
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.company_id == company_id)
            .where(Conversation.status == "open")
            .where(Conversation.mode.in_([ConversationMode.ai_active, ConversationMode.human_active]))
            .where(last_sender == "customer")
        )
        return int(self.db.scalar(stmt) or 0)

    def _approval_pending(self, company_id: uuid.UUID) -> int:
        return int(
            self.db.scalar(
                select(func.count())
                .select_from(ApprovalRequest)
                .where(ApprovalRequest.company_id == company_id)
                .where(ApprovalRequest.status == "pending")
            )
            or 0
        )

    def _ai_unsure(self, company_id: uuid.UUID) -> int:
        """Active requests where intake confidence was below 0.7 (AI not sure)."""
        stmt = (
            select(PartRequest)
            .where(PartRequest.company_id == company_id)
            .where(PartRequest.status.in_(_ACTIVE_PR_STATUSES))
        )
        count = 0
        for pr in self.db.scalars(stmt).unique().all():
            confidence = (pr.structured_data or {}).get("intent_confidence")
            if confidence is None:
                continue
            try:
                if float(confidence) < 0.7:
                    count += 1
            except (TypeError, ValueError):
                continue
        return count

    def _supplier_error(self, company_id: uuid.UUID) -> int:
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = (
            select(func.count())
            .select_from(SupplierSearchAttempt)
            .join(SupplierSearchRun, SupplierSearchAttempt.search_run_id == SupplierSearchRun.id)
            .where(SupplierSearchRun.part_request_id.in_(
                select(PartRequest.id).where(PartRequest.company_id == company_id)
            ))
            .where(SupplierSearchAttempt.status == SupplierAttemptStatus.failed)
            .where(SupplierSearchAttempt.created_at >= since)
        )
        return int(self.db.scalar(stmt) or 0)

    # --- 2. What AI already did today --------------------------------------

    def today(self, company_id: uuid.UUID) -> dict[str, int]:
        start = _day_start()
        return {
            "requests": self._count(
                PartRequest, PartRequest.company_id == company_id, PartRequest.created_at >= start
            ),
            "selections": self._count(
                SupplierSearchRun,
                SupplierSearchRun.part_request_id.in_(
                    select(PartRequest.id).where(PartRequest.company_id == company_id)
                ),
                SupplierSearchRun.status == SupplierSearchStatus.completed,
                SupplierSearchRun.completed_at >= start,
            ),
            "quotes": self._count(
                Quote, Quote.company_id == company_id, Quote.created_at >= start
            ),
            "sent": self._count(
                Quote,
                Quote.company_id == company_id,
                Quote.status.in_(_TERMINAL_QUOTE_STATUSES | {QuoteStatus.sent}),
                Quote.sent_at >= start,
            ),
            "orders": self._count(
                Order, Order.company_id == company_id, Order.created_at >= start
            ),
        }

    def _count(self, model, *conditions) -> int:
        stmt = select(func.count()).select_from(model)
        for condition in conditions:
            stmt = stmt.where(condition)
        return int(self.db.scalar(stmt) or 0)

    # --- 3. What to do right now -------------------------------------------

    def queue(self, company_id: uuid.UUID, limit: int = 20) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items.extend(self._queue_selection_ready(company_id))
        items.extend(self._queue_needs_reply(company_id))
        items.extend(self._queue_approval_pending(company_id))
        items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
        return items[:limit]

    def _queue_needs_reply(self, company_id: uuid.UUID, limit: int = 10) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for conversation in self._open_conversations(company_id, limit):
            messages = conversation.messages
            if not messages:
                continue
            last = messages[-1]
            if last.sender_type != "customer":
                continue
            items.append(
                {
                    "type": "needs_reply",
                    "action": "reply",
                    "title": "Клиент ждёт ответа",
                    "customer": self._customer_name(conversation),
                    "part": self._latest_part_name(conversation.id),
                    "vehicle": "",
                    "conversation_id": str(conversation.id),
                    "created_at": last.created_at.isoformat(),
                }
            )
        return items

    def _queue_approval_pending(self, company_id: uuid.UUID, limit: int = 10) -> list[dict[str, Any]]:
        stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.company_id == company_id)
            .where(ApprovalRequest.status == "pending")
            .order_by(ApprovalRequest.created_at.asc())
            .limit(limit)
        )
        items: list[dict[str, Any]] = []
        for approval in self.db.scalars(stmt).unique().all():
            quote = self.db.get(Quote, approval.quote_id) if approval.quote_id else None
            conversation = self.db.get(Conversation, approval.conversation_id) if approval.conversation_id else None
            part_request = self.db.get(PartRequest, quote.part_request_id) if quote else None
            items.append(
                {
                    "type": "approval_pending",
                    "action": "confirm",
                    "title": "Quote готов",
                    "customer": self._customer_name(conversation) if conversation else "",
                    "part": part_request.part_name if part_request else "",
                    "vehicle": self._vehicle_label(part_request) if part_request else "",
                    "conversation_id": str(approval.conversation_id) if approval.conversation_id else None,
                    "quote_id": str(approval.quote_id) if approval.quote_id else None,
                    "approval_id": str(approval.id),
                    "created_at": approval.created_at.isoformat(),
                }
            )
        return items

    def _queue_selection_ready(self, company_id: uuid.UUID, limit: int = 10) -> list[dict[str, Any]]:
        runs = (
            select(SupplierSearchRun)
            .where(SupplierSearchRun.status == SupplierSearchStatus.completed)
            .where(SupplierSearchRun.offers_found > 0)
            .where(
                SupplierSearchRun.part_request_id.in_(
                    select(PartRequest.id).where(PartRequest.company_id == company_id)
                )
            )
            .order_by(SupplierSearchRun.completed_at.desc())
            .limit(limit * 3)
        )
        items: list[dict[str, Any]] = []
        seen: set[uuid.UUID] = set()
        for run in self.db.scalars(runs).unique().all():
            pr = self.db.get(PartRequest, run.part_request_id)
            if pr is None or pr.id in seen:
                continue
            if pr.status not in _SELECTION_READY_PR_STATUSES:
                continue
            if self._has_sent_quote(pr.id):
                continue
            seen.add(pr.id)
            items.append(
                {
                    "type": "selection_ready",
                    "action": "open",
                    "title": f"AI подобрал {run.offers_found} вариантов",
                    "customer": pr.customer.name if pr.customer else "",
                    "part": pr.part_name,
                    "vehicle": self._vehicle_label(pr),
                    "conversation_id": str(pr.conversation_id),
                    "part_request_id": str(pr.id),
                    "created_at": run.completed_at.isoformat() if run.completed_at else pr.updated_at.isoformat(),
                }
            )
            if len(items) >= limit:
                break
        return items

    def _has_sent_quote(self, part_request_id: uuid.UUID) -> bool:
        stmt = (
            select(func.count())
            .select_from(Quote)
            .where(Quote.part_request_id == part_request_id)
            .where(Quote.status.in_(_TERMINAL_QUOTE_STATUSES | {QuoteStatus.sent}))
        )
        return int(self.db.scalar(stmt) or 0) > 0

    # --- Helpers ------------------------------------------------------------

    def _open_conversations(self, company_id: uuid.UUID, limit: int) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.company_id == company_id)
            .where(Conversation.status == "open")
            .where(Conversation.mode.in_([ConversationMode.ai_active, ConversationMode.human_active]))
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).unique().all())

    def _customer_name(self, conversation: Conversation) -> str:
        customer = self.db.get(Customer, conversation.customer_id)
        return customer.name if customer else ""

    def _latest_part_name(self, conversation_id: uuid.UUID) -> str:
        stmt = (
            select(PartRequest)
            .where(PartRequest.conversation_id == conversation_id)
            .order_by(PartRequest.created_at.desc())
            .limit(1)
        )
        pr = self.db.scalars(stmt).first()
        return pr.part_name if pr else ""

    @staticmethod
    def _vehicle_label(part_request: PartRequest | None) -> str:
        if part_request is None:
            return ""
        vehicle = part_request.vehicle
        if vehicle is None:
            return ""
        parts = []
        if vehicle.brand:
            parts.append(vehicle.brand)
        if vehicle.model:
            parts.append(vehicle.model)
        if vehicle.year:
            parts.append(str(vehicle.year))
        label = " ".join(parts)
        if vehicle.vin:
            label += f" (VIN {vehicle.vin})"
        return label

    # --- Assist Mode (sprint 3.8.2) -----------------------------------------

    def assist(self, company_id: uuid.UUID, days: int = 30) -> dict[str, Any]:
        """Manager edit rate: how often a quote is sent without changes.

        The higher ``manager_edit_rate``, the more the manager rubber-stamps
        the AI draft — that is the evidence base for turning on Controlled
        Auto. Counts come from AgentFeedback rows created on approval.
        """
        since = datetime.now(UTC) - timedelta(days=max(1, days))
        rows = self._rows(
            AgentFeedback,
            AgentFeedback.company_id == company_id,
            AgentFeedback.created_at >= since,
        )
        unchanged = sum(
            1 for fb in rows if fb.feedback_type == AgentFeedbackType.approved_unchanged
        )
        edited = sum(1 for fb in rows if fb.feedback_type == AgentFeedbackType.approved_edited)
        rejected = sum(1 for fb in rows if fb.feedback_type == AgentFeedbackType.rejected)
        total = unchanged + edited
        return {
            "window_days": days,
            "sends_total": total,
            "sends_unchanged": unchanged,
            "sends_edited": edited,
            "sends_rejected": rejected,
            "manager_edit_rate": round(unchanged / total * 100, 1) if total else None,
        }

    def _rows(self, model, *conditions) -> list:
        stmt = select(model).where(*conditions)
        return list(self.db.scalars(stmt).unique().all())

    def _shadow_stats(self, company_id: uuid.UUID) -> dict[str, Any]:
        from app.services.shadow_service import ShadowService

        return ShadowService(self.db).stats(company_id)
