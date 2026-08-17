from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import permissions
from app.core.config import settings
from app.models import (
    Agent,
    AgentAction,
    AgentFeedback,
    ApprovalRequest,
    Company,
    Conversation,
    Quote,
    SupplierOffer,
)
from app.models.enums import (
    AgentActionStatus,
    AgentFeedbackType,
    ApprovalStatus,
    QuoteStatus,
)
from app.services.audit_service import AuditService
from app.services.conversation_service import ConversationService
from app.services.quote_guard import quote_guard


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class ConflictError(Exception):
    pass


class GuardBlockedError(Exception):
    """QuoteGuard refused the message — it must not reach the customer."""

    def __init__(self, guard: dict[str, Any]) -> None:
        super().__init__("; ".join(guard.get("errors") or []))
        self.guard = guard


def _now() -> datetime:
    return datetime.now(UTC)


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return _now() > expires_at


def company_allowed(user, company_id) -> bool:
    """A user may only act on resources of their own company; a user without
    a company (unscoped) is treated as global."""
    from app.api.access import company_allowed as _company_allowed

    return _company_allowed(user, company_id)


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0")


class SalesService:
    """Owns the sales step of the pipeline (sprint 2.5).

    SalesAgent only formulates; SalesService + QuoteGuard decide. Sending to a
    customer is a MEDIUM-risk action, so it always goes through an
    ApprovalRequest before the message is created.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Draft (LOW risk — the agent acts alone) --------------------------

    def generate_draft(
        self,
        quote: Quote,
        *,
        agent_record=None,
        llm=None,
        task_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Let SalesAgent formulate the customer message, then verify it."""
        items = quote.items or []
        if not items:
            return {"error": "no_items", "message": "", "guard": {"passed": False}}

        message = self._build_message(quote, items, llm)
        guard = quote_guard.check(message, items, self._purchase_prices(quote))

        quote.ai_draft = message
        quote.guard_status = "pass" if guard.passed else "block"
        quote.guard_errors = guard.errors if not guard.passed else None

        if not guard.passed:
            # A draft contradicting the quote is a hallucination signal — it
            # feeds the quality report and the learning moat (sprint 3.2).
            self._record_hallucination(
                quote, message, agent_record.id if agent_record is not None else None
            )

        self._record_action(
            company_id=quote.company_id,
            action_type="prepare_sales_draft",
            agent_id=agent_record.id if agent_record is not None else None,
            task_id=task_id,
            target_type="quote",
            target_id=str(quote.id),
            input_data={"quote_id": str(quote.id)},
            result_data={"draft": message, "guard": guard.to_dict()},
            status=AgentActionStatus.executed,
        )
        self.db.flush()

        return {
            "message": message,
            "guard": guard.to_dict(),
            "recommended_offer_id": str(quote.best_offer_id) if quote.best_offer_id else None,
            "reason": "Лучшее сочетание цены и срока",
        }

    def save_edited(self, quote: Quote, message: str) -> Quote:
        quote.manager_edited = message.strip()
        return quote

    # --- Send + approval (MEDIUM risk — needs a human) --------------------

    def request_send(
        self,
        quote: Quote,
        message: str | None,
        user,
        *,
        agent_id: uuid.UUID | None = None,
        approve_now: bool = False,
    ) -> dict[str, Any]:
        """Prepare sending a quote message to the customer.

        QuoteGuard is re-checked on the final text; if it passes, an
        AgentAction + ApprovalRequest are created. ``approve_now`` performs the
        approval immediately (manager one-click send). Idempotent.
        """
        if not company_allowed(user, quote.company_id):
            raise ForbiddenError("Квота принадлежит другой компании.")

        final = (message or quote.manager_edited or quote.ai_draft or "").strip()
        if not final:
            raise ConflictError("Нет текста сообщения для отправки.")

        key = f"send_quote:{quote.id}:{quote.conversation_id}"
        existing = self._find_action_by_key(quote.company_id, key)
        if existing is not None and existing.status == AgentActionStatus.failed:
            # A corrected retry after a guard-blocked attempt: the old failed
            # row holds the UNIQUE key slot (legacy 3.8.x wrote guard-block
            # audits under the send key), so retire it before the real send —
            # INSERTing again would raise UniqueViolation (500 on live).
            self.db.delete(existing)
            self.db.flush()
            existing = None
        if existing is not None:
            if existing.status == AgentActionStatus.executed:
                return {
                    "already_executed": True,
                    "message_sent": True,
                    "status": "sent",
                    "quote_id": str(quote.id),
                }
            pending = self._approval_for_action(existing.id)
            if pending is not None:
                return {
                    "approval_id": str(pending.id),
                    "status": pending.status.value,
                    "message_sent": False,
                    "already_executed": False,
                    "quote_id": str(quote.id),
                }

        guard = quote_guard.check(final, quote.items or [], self._purchase_prices(quote))
        if not guard.passed:
            # Blocked sends are audited as failed actions (never trust the AI).
            # The audit insert uses a key that can never collide with the real
            # send (``key`` must stay free for a corrected retry): a second
            # blocked attempt of the same message is idempotent instead of
            # raising a UniqueViolation (post-3.8.3a UNIQUE idempotency key).
            audit_key = f"{key}:guard_blocked"
            recorded = self._find_action_by_key(quote.company_id, audit_key)
            if recorded is None:
                self._record_action(
                    company_id=quote.company_id,
                    action_type="send_customer_message",
                    agent_id=agent_id,
                    target_type="quote",
                    target_id=str(quote.id),
                    input_data={"quote_id": str(quote.id), "message": final},
                    result_data={"guard": guard.to_dict()},
                    status=AgentActionStatus.failed,
                    idempotency_key=audit_key,
                )
            self._record_hallucination(quote, final, agent_id)
            self.db.commit()
            raise GuardBlockedError(guard.to_dict())

        decision = permissions.evaluate(
            agent=agent_id,
            company=self.db.get(Company, quote.company_id),
            action="send_customer_message",
            resource="quote",
            context={"quote_id": str(quote.id), "conversation_id": str(quote.conversation_id)},
        )
        if decision.requires_approval:
            if decision.risk_level == "MEDIUM":
                # Sprint 3.8.3 — Controlled Auto, hardened in 3.8.3a:
                # decision -> latest quote reload -> QuoteGuard re-check ->
                # policy re-check -> ATOMIC send (unique idempotency key).
                auto_result = self._auto_send_safely(quote, final, agent_id)
                if auto_result is not None:
                    self.db.commit()
                    return auto_result
            action = self._record_action(
                company_id=quote.company_id,
                action_type="send_customer_message",
                agent_id=agent_id,
                target_type="quote",
                target_id=str(quote.id),
                input_data={"quote_id": str(quote.id), "message": final},
                status=AgentActionStatus.pending,
                idempotency_key=key,
            )
            approval = self._create_approval(quote, action, final, agent_id)
            quote.status = QuoteStatus.pending_approval

            if approve_now:
                return self.approve(approval.id, user)

            self.db.commit()
            return {
                "approval_id": str(approval.id),
                "status": ApprovalStatus.pending.value,
                "message_sent": False,
                "already_executed": False,
                "quote_id": str(quote.id),
            }

        # Company policy allows this action (LOW): the agent sends on its own.
        action = self._record_action(
            company_id=quote.company_id,
            action_type="send_customer_message",
            agent_id=agent_id,
            target_type="quote",
            target_id=str(quote.id),
            input_data={"quote_id": str(quote.id), "message": final},
            status=AgentActionStatus.executed,
            idempotency_key=key,
        )
        self._perform_send(quote, final, action=action)
        self.db.commit()
        return {
            "status": QuoteStatus.sent.value,
            "message_sent": True,
            "already_executed": False,
            "quote_id": str(quote.id),
        }

    def _auto_send_safely(
        self,
        quote: Quote,
        final: str,
        agent_id: uuid.UUID | None,
    ) -> dict[str, Any] | None:
        """Controlled Auto (3.8.3a): re-verify then atomically auto-send.

        Returns the send result when THIS worker won the race, ``None`` when
        the quote must go to a manager instead (unsafe / another worker owns
        the version). Never sends twice: the versioned idempotency key is
        UNIQUE in the DB, so a second worker's insert aborts.
        """
        fresh = self._reload_quote(quote)
        if fresh.status == QuoteStatus.sent:
            # Already delivered (e.g. a retry) — never send again.
            return {
                "already_executed": True,
                "message_sent": True,
                "status": "sent",
                "quote_id": str(fresh.id),
            }
        guard = quote_guard.check(final, fresh.items or [], self._purchase_prices(fresh))
        if not guard.passed:
            # The final text is no longer valid against the latest quote —
            # route to a manager instead of sending stale facts.
            return None
        auto = self._auto_send_decision(fresh)
        if not auto["auto"]:
            return None

        key = f"auto_send_quote:{fresh.id}:{fresh.version}"
        raced = self._find_action_by_key(fresh.company_id, key)
        if raced is not None:
            if raced.status == AgentActionStatus.executed:
                return {
                    "already_executed": True,
                    "message_sent": True,
                    "status": "sent",
                    "quote_id": str(fresh.id),
                }
            # Another worker holds a pending auto-send for this exact version:
            # do not double-send, do not create a stale approval — report in-flight.
            return {
                "approval_id": None,
                "status": ApprovalStatus.pending.value,
                "message_sent": False,
                "already_executed": False,
                "quote_id": str(fresh.id),
                "auto_in_flight": True,
            }
        try:
            action = self._record_action(
                company_id=fresh.company_id,
                action_type="send_customer_message",
                agent_id=agent_id,
                target_type="quote",
                target_id=str(fresh.id),
                input_data={"quote_id": str(fresh.id), "message": final},
                status=AgentActionStatus.pending,
                idempotency_key=key,
            )
            self.db.flush()
        except IntegrityError:
            # Unique key violated: another worker inserted the same version.
            self.db.rollback()
            raced = self._find_action_by_key(fresh.company_id, key)
            if raced is not None and raced.status == AgentActionStatus.executed:
                return {
                    "already_executed": True,
                    "message_sent": True,
                    "status": "sent",
                    "quote_id": str(fresh.id),
                }
            return {
                "approval_id": None,
                "status": ApprovalStatus.pending.value,
                "message_sent": False,
                "already_executed": False,
                "quote_id": str(fresh.id),
                "auto_in_flight": True,
            }

        self._perform_send(fresh, final, action=action, auto_send=auto)
        self._record_auto_audit(fresh, auto)
        fresh.version += 1
        return {
            "status": QuoteStatus.sent.value,
            "message_sent": True,
            "already_executed": False,
            "quote_id": str(fresh.id),
            "auto_sent": True,
            "auto_reasons": auto["reasons"],
        }

    def _reload_quote(self, quote: Quote) -> Quote:
        """Fetch the LATEST row for a quote inside the current transaction."""
        self.db.expire(quote)
        fresh = self.db.get(Quote, quote.id)
        if fresh is None:
            raise ConflictError("Квота не найдена.")
        return fresh

    def _record_auto_audit(self, quote: Quote, auto: dict[str, Any]) -> None:
        """Persist the full auto-send decision snapshot on the quote (3.8.3a)."""
        from app.services.auto_send_service import AutoSendService

        quote.auto_send_decision = AutoSendService(self.db).snapshot(auto)
        quote.auto_sent = True
        quote.auto_sent_at = _now()

    def _auto_send_decision(self, quote: Quote) -> dict[str, Any]:
        """Controlled Auto (sprint 3.8.3): only auto-send when it is safe.

        The decision is recorded on the send action so the pilot analytics can
        show how many quotes went out without a human and why.
        """
        from app.services.auto_send_service import AutoSendService

        return AutoSendService(self.db).decision(quote)

    def approve(self, approval_id: uuid.UUID, user) -> dict[str, Any]:
        approval = self._get_approval_or_raise(approval_id, user)

        if _is_expired(approval.expires_at):
            approval.status = ApprovalStatus.expired
            self.db.commit()
            raise ConflictError("Срок согласования истёк — запрос отклонён системой.")

        if approval.status == ApprovalStatus.approved:
            return self._already(approval)
        if approval.status != ApprovalStatus.pending:
            raise ConflictError(
                f"Запрос уже обработан (статус {approval.status.value})."
            )

        # Operational notifications (Sprint 4.6) — e.g. "Ваш заказ прибыл" —
        # have no quote; they dispatch to the order notification executor.
        if (approval.payload or {}).get("kind") == "order_notification":
            return self._approve_order_notification(approval, user)

        quote = self.db.get(Quote, approval.quote_id) if approval.quote_id else None
        if quote is None:
            raise ConflictError("Квота не найдена.")

        # 3.8.3a: a quote already delivered by auto-send must never be re-sent
        # through the approval path (double-send guard).
        if quote.status == QuoteStatus.sent:
            approval.status = ApprovalStatus.approved
            approval.approved_by_user_id = user.id
            approval.approved_at = _now()
            self.db.commit()
            return {
                "status": ApprovalStatus.approved.value,
                "message_sent": True,
                "message_id": None,
                "approval_id": str(approval.id),
                "already_approved": False,
                "already_sent": True,
            }

        final = (approval.payload or {}).get("message") or quote.manager_edited or quote.ai_draft
        if not final:
            raise ConflictError("Нет текста сообщения для отправки.")

        action = self.db.get(AgentAction, approval.action_id) if approval.action_id else None
        approval.status = ApprovalStatus.approved
        approval.approved_by_user_id = user.id
        approval.approved_at = _now()

        result = self._perform_send(quote, final, approval=approval, action=action)
        self._record_feedback(quote, approval, action, final)
        AuditService(self.db).record(
            action="approval.approve",
            entity_type="approval",
            entity_id=str(approval.id),
            company_id=approval.company_id,
            user_id=user.id,
            detail={"quote_id": str(quote.id) if quote.id else None},
        )
        self.db.commit()

        return {
            "status": ApprovalStatus.approved.value,
            "message_sent": True,
            "message_id": result["message_id"],
            "approval_id": str(approval.id),
            "already_approved": False,
        }

    def _approve_order_notification(
        self,
        approval: ApprovalRequest,
        user,
    ) -> dict[str, Any]:
        """Deliver an operational order notification ("Ваш заказ прибыл").

        Approval payload: ``{kind: "order_notification", order_id, message}``.
        The message is written into the customer's conversation and the action
        is marked executed. No quote/feedback involved.
        """
        from app.models import Order

        payload = approval.payload or {}
        order = (
            self.db.get(Order, uuid.UUID(str(payload["order_id"])))
            if payload.get("order_id")
            else None
        )
        if order is None:
            raise ConflictError("Заказ уведомления не найден.")
        conversation = (
            self.db.get(Conversation, order.conversation_id)
            if order.conversation_id
            else None
        )
        if conversation is None:
            raise ConflictError("Диалог клиента не найден.")

        approval.status = ApprovalStatus.approved
        approval.approved_by_user_id = user.id
        approval.approved_at = _now()

        action = self.db.get(AgentAction, approval.action_id) if approval.action_id else None

        message = payload.get("message") or (
            f"Ваш заказ {order.order_number} прибыл в автосервис и готов к выдаче."
        )
        msg, _ = ConversationService(self.db).add_message(
            conversation,
            content=message,
            sender_type="agent",
            sender_id=None,
            structured_data={
                "kind": "order_notification",
                "order_id": str(order.id),
                "approval_id": str(approval.id),
                "action_id": str(action.id) if action else None,
            },
        )
        if action is not None:
            action.status = AgentActionStatus.executed
            action.executed_at = _now()
            action.result_data = {
                "message_id": str(msg.id),
                "order_id": str(order.id),
                "approval_id": str(approval.id),
            }

        AuditService(self.db).record(
            action="approval.approve",
            entity_type="approval",
            entity_id=str(approval.id),
            company_id=approval.company_id,
            user_id=user.id,
            detail={
                "kind": "order_notification",
                "order_id": str(order.id),
                "order_number": order.order_number,
            },
        )
        self.db.commit()
        return {
            "status": ApprovalStatus.approved.value,
            "message_sent": True,
            "message_id": str(msg.id),
            "approval_id": str(approval.id),
            "already_approved": False,
        }

    def _perform_send(
        self,
        quote: Quote,
        message: str,
        *,
        approval: ApprovalRequest | None = None,
        action: AgentAction | None = None,
        auto_send: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Actually deliver the sales message to the customer.

        Shared by the manager-approval path and the PermissionEngine
        auto-send path (LOW risk). QuoteGuard is always re-checked — we
        never trust a previously validated text.
        """
        guard = quote_guard.check(message, quote.items or [], self._purchase_prices(quote))
        if not guard.passed:
            raise GuardBlockedError(guard.to_dict())

        conversation = (
            self.db.get(Conversation, quote.conversation_id) if quote.conversation_id else None
        )
        if conversation is None:
            raise ConflictError("Диалог клиента не найден.")

        msg, _ = ConversationService(self.db).add_message(
            conversation,
            content=message,
            sender_type="agent",
            sender_id=None,
            structured_data={
                "kind": "sales",
                "quote_id": str(quote.id),
                "approval_id": str(approval.id) if approval else None,
                "action_id": str(action.id) if action else None,
            },
        )

        quote.status = QuoteStatus.sent
        quote.final_message = message
        quote.sent_at = _now()

        if action is not None:
            action.status = AgentActionStatus.executed
            action.executed_at = _now()
            action.result_data = {
                "message_id": str(msg.id),
                "approval_id": str(approval.id) if approval else None,
                **({"auto_send": auto_send} if auto_send is not None else {}),
            }

        return {"message_id": str(msg.id), "approval_id": str(approval.id) if approval else None}

    def reject(
        self, approval_id: uuid.UUID, user, reason: str = ""
    ) -> dict[str, Any]:
        approval = self._get_approval_or_raise(approval_id, user)

        if _is_expired(approval.expires_at):
            approval.status = ApprovalStatus.expired
            self.db.commit()
            raise ConflictError("Срок согласования истёк.")

        if approval.status == ApprovalStatus.rejected:
            return {
                "status": ApprovalStatus.rejected.value,
                "message_sent": False,
                "already_rejected": True,
                "approval_id": str(approval.id),
            }
        if approval.status != ApprovalStatus.pending:
            raise ConflictError(f"Запрос уже обработан (статус {approval.status.value}).")

        quote = self.db.get(Quote, approval.quote_id) if approval.quote_id else None
        if quote is not None and quote.status == QuoteStatus.pending_approval:
            quote.status = QuoteStatus.draft  # вернуть к правке, не отправлять

        approval.status = ApprovalStatus.rejected
        approval.rejected_by_user_id = user.id
        approval.rejected_at = _now()
        approval.rejection_reason = reason or None

        action = self.db.get(AgentAction, approval.action_id) if approval.action_id else None
        if action is not None:
            action.status = AgentActionStatus.cancelled

        # Operational notifications (order arrival) carry no quote — skipping
        # the sales feedback record keeps their lifecycle purely operational.
        if (approval.payload or {}).get("kind") != "order_notification":
            self._record_feedback(quote, approval, action, final_output=None, rejected=True)
        AuditService(self.db).record(
            action="approval.reject",
            entity_type="approval",
            entity_id=str(approval.id),
            company_id=approval.company_id,
            user_id=user.id,
            detail={"reason": reason or None},
        )
        self.db.commit()

        return {
            "status": ApprovalStatus.rejected.value,
            "message_sent": False,
            "approval_id": str(approval.id),
            "already_rejected": False,
        }

    def quote_reject(self, quote: Quote, user, reason: str = "") -> dict[str, Any]:
        """Manager declines the AI proposal before any send request."""
        if not company_allowed(user, quote.company_id):
            raise ForbiddenError("Квота принадлежит другой компании.")
        pending = self._find_pending_approval(quote.id)
        if pending is not None:
            return self.reject(pending.id, user, reason or "Отклонено менеджером")
        self.db.add(
            AgentFeedback(
                company_id=quote.company_id,
                feedback_type=AgentFeedbackType.rejected,
                original_output=quote.ai_draft,
                final_output=None,
                prompt_version=quote.prompt_version,
            )
        )
        quote.status = QuoteStatus.draft
        self.db.commit()
        return {"status": "rejected", "reason": reason, "quote_id": str(quote.id)}

    # --- Read models --------------------------------------------------------

    def sales_draft_info(self, quote: Quote) -> dict[str, Any]:
        return {
            "quote_id": str(quote.id),
            "part_request_id": str(quote.part_request_id),
            "conversation_id": str(quote.conversation_id),
            "status": quote.status.value,
            "currency": quote.currency,
            "quote_total": str(quote.quote_total) if quote.quote_total is not None else None,
            "best_offer_id": str(quote.best_offer_id) if quote.best_offer_id else None,
            "items": quote.items,
            "ai_draft": quote.ai_draft,
            "manager_edited": quote.manager_edited,
            "final_message": quote.final_message,
            "guard_status": quote.guard_status,
            "guard_errors": quote.guard_errors,
            "prompt_version": quote.prompt_version,
            "sent_at": quote.sent_at.isoformat() if quote.sent_at else None,
            "created_at": quote.created_at.isoformat(),
        }

    def list_approvals(self, company_id=None, limit: int = 100) -> list[ApprovalRequest]:
        stmt = select(ApprovalRequest).order_by(
            ApprovalRequest.created_at.desc()
        )
        if company_id:
            stmt = stmt.where(ApprovalRequest.company_id == company_id)
        return list(self.db.scalars(stmt.limit(limit)).unique().all())

    def get_approval(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        return self.db.get(ApprovalRequest, approval_id)

    def list_actions(self, company_id=None, limit: int = 100) -> list[AgentAction]:
        stmt = select(AgentAction).order_by(AgentAction.created_at.desc())
        if company_id:
            stmt = stmt.where(AgentAction.company_id == company_id)
        return list(self.db.scalars(stmt.limit(limit)).unique().all())

    def get_action(self, action_id: uuid.UUID) -> AgentAction | None:
        return self.db.get(AgentAction, action_id)

    # --- Internals ---------------------------------------------------------

    def _build_message(self, quote: Quote, items: list[dict[str, Any]], llm) -> str:
        if llm is not None and getattr(llm, "available", False):
            draft = self._llm_draft(quote, items, llm)
            if draft and quote_guard.check(draft, items, self._purchase_prices(quote)).passed:
                return draft
        return self._template(quote, items)

    def _llm_draft(self, quote: Quote, items: list[dict[str, Any]], llm) -> str | None:
        from app.llm.types import LLMMessage
        from app.services.prompt_service import PromptService

        data = [
            {
                "brand": it.get("brand"),
                "article": it.get("article"),
                "sale_price": it.get("sale_price"),
                "total_price": it.get("total_price"),
                "delivery_days": it.get("delivery_days"),
                "quantity_available": it.get("quantity_available"),
            }
            for it in items
        ]
        system_prompt, version = PromptService(self.db).active_prompt(
            "sales", quote.company_id
        )
        # Stamp which prompt version produced this draft — the key to comparing
        # quality across prompt versions (sprint 3.2).
        quote.prompt_version = version
        user_prompt = (
            f"Квота (клиентская информация):\n{data}\n"
            "Составь сообщение клиенту."
        )
        try:
            result = llm.chat(
                messages=[
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ],
                model=getattr(llm, "model", None),
                temperature=0.2,
                max_tokens=400,
            )
        except Exception:
            return None
        if result is None or not result.content:
            return None
        return result.content.strip()

    def _template(self, quote: Quote, items: list[dict[str, Any]]) -> str:
        ordered = sorted(
            items,
            key=lambda it: _dec(it.get("total_price") or it.get("sale_price")),
        )
        best = str(quote.best_offer_id)
        lines: list[str] = []
        for it in ordered:
            mark = "⭐ " if str(it.get("offer_id")) == best else "• "
            facts: list[str] = []
            days = it.get("delivery_days")
            avail = it.get("quantity_available")
            if days is not None:
                facts.append(f"срок {days} дн.")
            if avail is not None:
                facts.append(f"в наличии {avail} шт")
            suffix = f" ({', '.join(facts)})" if facts else ""
            lines.append(
                f"{mark}{it.get('brand', '')} {it.get('article', '')} — "
                f"{self._money(it.get('sale_price'))} ₽{suffix}"
            )
        return (
            "Здравствуйте! Подобрал для вас варианты:\n"
            + "\n".join(lines)
            + "\nКакой вариант вам подходит?"
        )

    @staticmethod
    def _money(value: Any) -> str:
        amount = _dec(value)
        if amount == amount.to_integral():
            text = f"{int(amount):,}"
        else:
            text = f"{amount:,.2f}".rstrip("0").rstrip(".")
        return text.replace(",", " ")

    def _purchase_prices(self, quote: Quote) -> list[Decimal | None]:
        stmt = select(SupplierOffer).where(
            SupplierOffer.part_request_id == quote.part_request_id
        )
        return [o.purchase_price for o in self.db.scalars(stmt).unique().all()]

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
        idempotency_key: str | None = None,
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
            idempotency_key=idempotency_key,
            executed_at=_now() if status == AgentActionStatus.executed else None,
        )
        self.db.add(action)
        self.db.flush()
        return action

    def _create_approval(
        self,
        quote: Quote,
        action: AgentAction,
        message: str,
        agent_id=None,
    ) -> ApprovalRequest:
        expires_at = _now() + timedelta(hours=settings.approval_ttl_hours)
        approval = ApprovalRequest(
            company_id=quote.company_id,
            conversation_id=quote.conversation_id,
            quote_id=quote.id,
            action_id=action.id,
            action_type=action.action_type,
            status=ApprovalStatus.pending,
            payload={"quote_id": str(quote.id), "message": message},
            risk_level=action.risk_level,
            requested_by_agent_id=agent_id,
            expires_at=expires_at,
        )
        self.db.add(approval)
        self.db.flush()
        from app.tracing.tracer import record_span, resolve_trace_for_conversation

        trace_id = resolve_trace_for_conversation(
            self.db,
            quote.conversation_id,
            company_id=quote.company_id,
            source="approval",
        )
        if trace_id is not None:
            record_span(
                self.db,
                "approval",
                f"Согласование: {action.action_type}",
                trace_id=trace_id,
                status="ok",
                metadata={
                    "approval_id": str(approval.id),
                    "quote_id": str(quote.id),
                },
            )
        return approval

    def _record_feedback(
        self,
        quote: Quote | None,
        approval: ApprovalRequest,
        action: AgentAction | None,
        final_output: str | None,
        rejected: bool = False,
    ) -> None:
        original = (quote.ai_draft if quote is not None else None) or ""
        if rejected:
            feedback_type = AgentFeedbackType.rejected
        else:
            final = final_output or ""
            feedback_type = (
                AgentFeedbackType.approved_edited
                if original and final and final != original
                else AgentFeedbackType.approved_unchanged
            )
        self.db.add(
            AgentFeedback(
                company_id=approval.company_id,
                agent_id=approval.requested_by_agent_id or self._sales_agent_id(approval.company_id),
                task_id=approval.task_id,
                action_id=approval.action_id,
                feedback_type=feedback_type,
                original_output=original,
                final_output=final_output,
                prompt_version=quote.prompt_version if quote is not None else None,
            )
        )
        # Fitment Engine (sprint 4.0): a manager approving the AI's pick
        # unchanged confirms the fitment — feed the learning moat.
        if (
            quote is not None
            and feedback_type == AgentFeedbackType.approved_unchanged
            and quote.part_request_id is not None
        ):
            from app.models import PartRequest
            from app.services.fitment_service import FitmentService

            pr = self.db.get(PartRequest, quote.part_request_id)
            if pr is not None:
                FitmentService(self.db).record_manager_evidence(
                    pr,
                    source="manager_confirmation",
                    confidence=0.95,
                    detail={"approval_id": str(approval.id)},
                )

    def _record_hallucination(
        self,
        quote: Quote,
        output: str,
        agent_id=None,
    ) -> None:
        """A QuoteGuard block means the agent's text contradicted the quote —
        recorded as incorrect_fact feedback so hallucination_rate is real."""
        self.db.add(
            AgentFeedback(
                company_id=quote.company_id,
                agent_id=agent_id or self._sales_agent_id(quote.company_id),
                feedback_type=AgentFeedbackType.incorrect_fact,
                original_output=output,
                final_output=None,
                prompt_version=quote.prompt_version,
            )
        )

    def _sales_agent_id(self, company_id) -> uuid.UUID | None:
        """Attribute output reviews to the company's SalesAgent even when the
        send/approve API call did not carry an agent id."""
        stmt = select(Agent).where(
            Agent.company_id == company_id,
            Agent.slug == "sales-agent",
        )
        agent = self.db.scalars(stmt).first()
        return agent.id if agent is not None else None

    def _get_approval_or_raise(self, approval_id: uuid.UUID, user) -> ApprovalRequest:
        approval = self.db.get(ApprovalRequest, approval_id)
        if approval is None:
            raise NotFoundError("Запрос на согласование не найден.")
        if not company_allowed(user, approval.company_id):
            raise ForbiddenError("Запрос принадлежит другой компании.")
        return approval

    def _find_action_by_key(self, company_id, key: str) -> AgentAction | None:
        stmt = (
            select(AgentAction)
            .where(AgentAction.company_id == company_id)
            .where(AgentAction.idempotency_key == key)
            .order_by(AgentAction.created_at.desc())
        )
        return self.db.scalars(stmt).first()

    def _approval_for_action(self, action_id) -> ApprovalRequest | None:
        stmt = select(ApprovalRequest).where(ApprovalRequest.action_id == action_id)
        return self.db.scalars(stmt).first()

    def _find_pending_approval(self, quote_id) -> ApprovalRequest | None:
        stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.quote_id == quote_id)
            .where(ApprovalRequest.status == ApprovalStatus.pending)
            .order_by(ApprovalRequest.created_at.desc())
        )
        return self.db.scalars(stmt).first()

    @staticmethod
    def _already(approval: ApprovalRequest) -> dict[str, Any]:
        return {
            "status": ApprovalStatus.approved.value,
            "message_sent": True,
            "approval_id": str(approval.id),
            "already_approved": True,
        }
