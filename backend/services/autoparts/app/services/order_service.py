from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import permissions
from app.models import AgentAction, Company, Conversation, Order, PartRequest, Quote
from app.models.enums import AgentActionStatus, OrderStatus, QuoteStatus
from app.services.audit_service import AuditService
from app.services.sales_service import (
    ConflictError,
    ForbiddenError,
    company_allowed,
)

# Customer acceptance detection: an accepted quote can be converted to an
# order. Only positive confirmations count; a negated reply ("нет, не подходит")
# must never flip a quote to `accepted`.
_ACCEPT_RE = re.compile(
    r"(да,?\s*беру|да,?\s*заказ|беру\b|забираю\b|заказыва\w+|подходит\b|"
    r"соглас\w+|оформля\w+|подтвержда\w+|оплач\w+|да\b|ок\b)",
    re.IGNORECASE,
)
_NEGATE_RE = re.compile(
    r"(не подходит|не беру|не надо|не буду|не заказы|не соглас|отказ\w*|нет,?\s*спасибо)",
    re.IGNORECASE,
)


def _now() -> datetime:
    return datetime.now(UTC)


class OrderService:
    """Completes the quote funnel (sprint 2.6).

    acceptance (LOW — the agent may record it) and conversion into an order
    (HIGH — only a human creates an order). Every transition is audited as an
    AgentAction so the funnel stays fully traceable.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Acceptance (LOW risk — agent records the customer's decision) -----

    def accept(
        self,
        quote: Quote,
        user=None,
        *,
        agent_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Mark a sent quote as accepted by the customer."""
        from app.tracing.tracer import record_span, resolve_trace_for_conversation

        trace_id = resolve_trace_for_conversation(
            self.db,
            quote.conversation_id,
            company_id=quote.company_id,
            source="quote_accept",
        )
        try:
            result = self._accept(quote, user, agent_id=agent_id, task_id=task_id)
        except Exception as exc:
            if trace_id is not None:
                record_span(
                    self.db,
                    "order",
                    f"Принятие квоты {quote.id}",
                    trace_id=trace_id,
                    status="failed",
                    error_kind=type(exc).__name__,
                    metadata={"quote_id": str(quote.id)},
                )
            raise
        if trace_id is not None:
            record_span(
                self.db,
                "order",
                f"Принятие квоты {quote.id}",
                trace_id=trace_id,
                status="ok",
                metadata={"quote_id": str(quote.id), "status": result.get("status")},
            )
        return result

    def _accept(
        self,
        quote: Quote,
        user=None,
        *,
        agent_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        if not company_allowed(user, quote.company_id):
            raise ForbiddenError("Квота принадлежит другой компании.")
        if quote.status == QuoteStatus.accepted:
            return {
                "quote_id": str(quote.id),
                "status": QuoteStatus.accepted.value,
                "already_accepted": True,
            }
        if quote.status != QuoteStatus.sent:
            raise ConflictError(
                "Квота ещё не отправлена клиенту — принятие недоступно."
            )

        quote.status = QuoteStatus.accepted
        self._record_action(
            company_id=quote.company_id,
            action_type="accept_quote",
            agent_id=agent_id,
            task_id=task_id,
            target_type="quote",
            target_id=str(quote.id),
            input_data={"quote_id": str(quote.id)},
            result_data={"status": QuoteStatus.accepted.value},
            status=AgentActionStatus.executed,
        )
        AuditService(self.db).record(
            action="quote.accept",
            entity_type="quote",
            entity_id=str(quote.id),
            company_id=quote.company_id,
            user_id=user.id if user is not None else None,
            actor_type="user" if user is not None else "agent",
            detail={"quote_id": str(quote.id)},
        )
        self.db.commit()
        return {
            "quote_id": str(quote.id),
            "status": QuoteStatus.accepted.value,
            "already_accepted": False,
        }

    def accept_if_customer_confirms(
        self,
        conversation: Conversation,
        customer_content: str,
        *,
        agent_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """Auto-detect a positive customer reply to a sent quote.

        Called from ConversationService.add_message on incoming customer text.
        Returns the accept() result or None when the quote isn't awaiting
        acceptance (sent) or the reply doesn't confirm it.
        """
        if _NEGATE_RE.search(customer_content):
            return None
        if not _ACCEPT_RE.search(customer_content):
            return None
        quote = self._sent_quote_for_conversation(conversation.id)
        if quote is None:
            return None
        return self.accept(quote, user=None, agent_id=agent_id)

    # --- Order creation (HIGH risk — only a human) -------------------------

    def create_from_quote(
        self,
        quote: Quote,
        user,
        *,
        agent_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Convert an accepted quote into an Order (manager-only)."""
        from app.tracing.tracer import record_span, resolve_trace_for_conversation

        trace_id = resolve_trace_for_conversation(
            self.db,
            quote.conversation_id,
            company_id=quote.company_id,
            source="order_create",
        )
        try:
            result = self._create_from_quote(
                quote, user, agent_id=agent_id, task_id=task_id
            )
        except Exception as exc:
            if trace_id is not None:
                record_span(
                    self.db,
                    "order",
                    f"Создание заказа по квоте {quote.id}",
                    trace_id=trace_id,
                    status="failed",
                    error_kind=type(exc).__name__,
                    metadata={"quote_id": str(quote.id)},
                )
            raise
        order_id = result.get("order_id")
        if order_id is not None and not isinstance(order_id, uuid.UUID):
            try:
                order_id = uuid.UUID(str(order_id))
            except (ValueError, TypeError):
                order_id = None
        if trace_id is not None:
            record_span(
                self.db,
                "order",
                f"Заказ {result.get('order_number') or order_id}",
                trace_id=trace_id,
                order_id=order_id,
                status="ok",
                metadata={"quote_id": str(quote.id)},
            )
        return result

    def _create_from_quote(
        self,
        quote: Quote,
        user,
        *,
        agent_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        if not company_allowed(user, quote.company_id):
            raise ForbiddenError("Квота принадлежит другой компании.")
        if user is None or not user.is_superuser:
            raise ForbiddenError(
                "Создание заказа — действие высокого риска, доступно только менеджеру."
            )

        if quote.status == QuoteStatus.converted_to_order:
            existing = self._order_for_quote(quote.id)
            if existing is not None:
                return {
                    "order_id": str(existing.id),
                    "order_number": existing.order_number,
                    "quote_id": str(quote.id),
                    "status": QuoteStatus.converted_to_order.value,
                    "already_converted": True,
                }

        if quote.status not in (QuoteStatus.sent, QuoteStatus.accepted):
            raise ConflictError(
                "Квота не принята клиентом — заказ нельзя создать."
            )

        part_request = self.db.get(PartRequest, quote.part_request_id)
        customer_id = part_request.customer_id if part_request is not None else None
        if customer_id is None:
            raise ConflictError("Не найден клиент заявки.")

        order = Order(
            company_id=quote.company_id,
            conversation_id=quote.conversation_id,
            customer_id=customer_id,
            part_request_id=quote.part_request_id,
            quote_id=quote.id,
            order_number=self._next_order_number(quote.company_id),
            status=OrderStatus.new,
            currency=quote.currency or "RUB",
            order_total=quote.quote_total,
            items=quote.items or [],
            created_by_user_id=user.id,
        )
        self.db.add(order)
        self.db.flush()

        # Fitment Engine (sprint 4.0): a confirmed order is the strongest
        # positive evidence that this article fits this vehicle — the engine
        # must never re-learn it from scratch on the next identical request.
        from app.services.fitment_service import FitmentService

        FitmentService(self.db).record_order_evidence(part_request, order)

        # Supplier Intelligence (sprint 4.2): snapshot what each supplier
        # promised on every order line, then refresh the live rating.
        from app.services.supplier_reliability_service import (
            SupplierReliabilityService,
        )

        SupplierReliabilityService(self.db).record_fulfillments_for_order(order)

        quote.status = QuoteStatus.converted_to_order
        self._record_action(
            company_id=quote.company_id,
            action_type="create_order",
            agent_id=agent_id,
            task_id=task_id,
            target_type="quote",
            target_id=str(quote.id),
            input_data={"quote_id": str(quote.id)},
            result_data={"order_id": str(order.id), "order_number": order.order_number},
            status=AgentActionStatus.executed,
        )

        from app.services.conversation_service import ConversationService

        conversation = self.db.get(Conversation, quote.conversation_id)
        if conversation is not None:
            ConversationService(self.db).add_message(
                conversation,
                content=(
                    f"Заказ {order.order_number} оформлен "
                    f"(сумма {order.order_total} {order.currency}). "
                    "Спасибо за доверие!"
                ),
                sender_type="agent",
                sender_id=None,
                structured_data={
                    "kind": "order",
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                    "quote_id": str(quote.id),
                },
            )

        AuditService(self.db).record(
            action="order.create",
            entity_type="order",
            entity_id=str(order.id),
            company_id=order.company_id,
            user_id=user.id if user is not None else None,
            detail={
                "order_number": order.order_number,
                "quote_id": str(quote.id),
                "total": str(order.order_total),
                "currency": order.currency,
            },
        )

        # Supplier Order Automation (Sprint 4.5): the moment an order exists the
        # agent may *ask* to buy the parts, but the purchase stays HIGH-risk —
        # an ApprovalRequest is raised per supplier and the external order is
        # only placed after a manager approves it.
        from app.services.supplier_order_service import SupplierOrderService

        SupplierOrderService(self.db).request_purchase(order, agent_id=agent_id)

        self.db.commit()
        return {
            "order_id": str(order.id),
            "order_number": order.order_number,
            "quote_id": str(quote.id),
            "status": QuoteStatus.converted_to_order.value,
            "already_converted": False,
        }

    # --- Read models ---------------------------------------------------------

    def list_orders(self, company_id=None, limit: int = 100) -> list[Order]:
        stmt = select(Order).order_by(Order.created_at.desc())
        if company_id:
            stmt = stmt.where(Order.company_id == company_id)
        return list(self.db.scalars(stmt.limit(limit)).unique().all())

    def get_order(self, order_id: uuid.UUID) -> Order | None:
        return self.db.get(Order, order_id)

    # --- Internals ---------------------------------------------------------

    def _sent_quote_for_conversation(
        self, conversation_id: uuid.UUID
    ) -> Quote | None:
        stmt = (
            select(Quote)
            .where(Quote.conversation_id == conversation_id)
            .where(Quote.status == QuoteStatus.sent)
            .order_by(Quote.created_at.desc())
        )
        return self.db.scalars(stmt).first()

    def _order_for_quote(self, quote_id: uuid.UUID) -> Order | None:
        stmt = select(Order).where(Order.quote_id == quote_id)
        return self.db.scalars(stmt).first()

    def _next_order_number(self, company_id: uuid.UUID) -> str:
        count = (
            self.db.scalars(
                select(Order).where(Order.company_id == company_id)
            ).all()
        )
        return f"ORD-{len(count) + 1:04d}-{uuid.uuid4().hex[:6].upper()}"

    def _record_action(
        self,
        *,
        company_id,
        action_type: str,
        agent_id=None,
        task_id=None,
        target_type: str | None = None,
        target_id: str | None = None,
        input_data=None,
        result_data=None,
        risk=None,
        requires: bool | None = None,
        status: AgentActionStatus = AgentActionStatus.pending,
    ) -> AgentAction:
        company = self.db.get(Company, company_id) if company_id else None
        action = AgentAction(
            company_id=company_id,
            agent_id=agent_id,
            task_id=task_id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            input_data=input_data,
            result_data=result_data,
            risk_level=(
                risk if risk is not None else permissions.risk_for(action_type, target_type, company)
            ),
            requires_approval=(
                requires
                if requires is not None
                else permissions.requires_approval_for(action_type, target_type, company)
            ),
            status=status,
            executed_at=_now() if status == AgentActionStatus.executed else None,
        )
        self.db.add(action)
        self.db.flush()
        return action
