from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import permissions
from app.core.config import settings
from app.models import (
    AgentAction,
    ApprovalRequest,
    Company,
    Conversation,
    Order,
    Supplier,
    SupplierFulfillment,
    SupplierOffer,
)
from app.models.enums import (
    AgentActionStatus,
    ApprovalRiskLevel,
    ApprovalStatus,
    OrderStatus,
    TrackingStatus,
)
from app.services.audit_service import AuditService
from app.services.sales_service import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    company_allowed,
)
from app.services.supplier_service import SupplierService
from app.suppliers.base import SupplierOrderData
from app.suppliers.errors import SupplierAdapterError

# The action name must stay in sync with DEFAULT_POLICIES (HIGH risk).
_ORDER_ACTION = "send_supplier_order"

# Supplier-side statuses map onto the customer-facing tracking milestones.
# The rank is the progress; the aggregate of an order is the most advanced
# supplier line. "delivered" (legacy mock) == "arrived".
_TRACKING_ORDER = [
    TrackingStatus.pending.value,
    TrackingStatus.accepted.value,
    TrackingStatus.assembling.value,
    TrackingStatus.shipped.value,
    TrackingStatus.arrived.value,
]
_SUPPLIER_TO_RANK = {
    "accepted": 1,
    "assembling": 2,
    "shipped": 3,
    "arrived": 4,
    "delivered": 4,
}

TRACKING_LABELS = {
    TrackingStatus.pending.value: "Заказ не размещён",
    TrackingStatus.accepted.value: "Заказ принят",
    TrackingStatus.assembling.value: "В сборке",
    TrackingStatus.shipped.value: "Отправлен",
    TrackingStatus.arrived.value: "Прибыл",
    TrackingStatus.handed_over.value: "Выдан клиенту",
}


def _now() -> datetime:
    return datetime.now(UTC)


class SupplierOrderService:
    """Owns the purchase side of an order (Sprint 4.5).

    After an order is created from an accepted quote the agent may *ask* to buy
    the parts, but never spends money alone: ``send_supplier_order`` is a HIGH
    risk action, so every request lands in an ApprovalRequest. Only when a
    manager approves does the supplier adapter actually place the order and the
    external tracking id is stamped on the fulfillment lines.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Request (auto — HIGH risk → human approval) ----------------------

    def request_purchase(
        self,
        order: Order,
        *,
        agent_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Ask to purchase every supplier group of the order.

        Idempotent: each (order, supplier) pair yields at most one pending or
        already-executed purchase request. One ApprovalRequest per supplier
        that participates in the order.
        """
        results: list[dict[str, Any]] = []
        for supplier_id, items in self._supplier_groups(order):
            supplier = self.db.get(Supplier, supplier_id)
            if supplier is None or not supplier.is_active:
                continue
            results.append(
                self._request_for_supplier(order, supplier, items, agent_id=agent_id)
            )
        self.db.flush()
        return results

    def _request_for_supplier(
        self,
        order: Order,
        supplier: Supplier,
        items: list[dict[str, Any]],
        *,
        agent_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        key = f"supplier_order:{order.id}:{supplier.id}"
        existing = self._find_action_by_key(order.company_id, key)
        if existing is not None:
            if existing.status == AgentActionStatus.executed:
                return {
                    "supplier_id": str(supplier.id),
                    "supplier_name": supplier.name,
                    "status": "ordered",
                    "already_executed": True,
                    "approval_id": None,
                }
            pending = self._approval_for_action(existing.id)
            if pending is not None:
                return {
                    "supplier_id": str(supplier.id),
                    "supplier_name": supplier.name,
                    "status": pending.status.value,
                    "already_executed": False,
                    "approval_id": str(pending.id),
                }

        action = AgentAction(
            company_id=order.company_id,
            agent_id=agent_id,
            action_type=_ORDER_ACTION,
            target_type="order",
            target_id=str(order.id),
            input_data={
                "order_id": str(order.id),
                "supplier_id": str(supplier.id),
                "items": items,
            },
            risk_level=permissions.risk_for(_ORDER_ACTION, "order", None),
            requires_approval=permissions.requires_approval_for(
                _ORDER_ACTION, "order", None
            ),
            status=AgentActionStatus.pending,
            idempotency_key=key,
        )
        self.db.add(action)
        self.db.flush()

        approval = ApprovalRequest(
            company_id=order.company_id,
            conversation_id=order.conversation_id,
            quote_id=order.quote_id,
            action_id=action.id,
            action_type=_ORDER_ACTION,
            status=ApprovalStatus.pending,
            payload={
                "order_id": str(order.id),
                "supplier_id": str(supplier.id),
                "items": items,
                "order_total": (
                    str(order.order_total) if order.order_total is not None else None
                ),
            },
            risk_level=permissions.risk_for(_ORDER_ACTION, "order", None),
            requested_by_agent_id=agent_id,
            expires_at=_now() + timedelta(hours=settings.approval_ttl_hours),
        )
        self.db.add(approval)
        self.db.flush()
        return {
            "supplier_id": str(supplier.id),
            "supplier_name": supplier.name,
            "status": ApprovalStatus.pending.value,
            "already_executed": False,
            "approval_id": str(approval.id),
        }

    # --- Approve / reject (HIGH — only a human) ---------------------------

    async def approve_purchase(
        self,
        approval_id: uuid.UUID,
        user,
    ) -> dict[str, Any]:
        """Approve a supplier purchase and place the external order."""
        approval = self._get_approval_or_raise(approval_id, user)
        self._require_manager(user)
        self._ensure_order_action(approval)

        if self._is_expired(approval):
            approval.status = ApprovalStatus.expired
            self.db.commit()
            raise ConflictError("Срок согласования истёк — закупка не выполнена.")

        if approval.status == ApprovalStatus.approved:
            return {
                "approval_id": str(approval.id),
                "status": ApprovalStatus.approved.value,
                "already_approved": True,
                "external_order_id": self._external_order_id(approval),
                "order_status": self._order_status(approval),
            }
        if approval.status != ApprovalStatus.pending:
            raise ConflictError(
                f"Запрос уже обработан (статус {approval.status.value})."
            )

        order = self.db.get(Order, uuid.UUID(str(approval.payload["order_id"])))
        supplier = self.db.get(Supplier, uuid.UUID(str(approval.payload["supplier_id"])))
        if order is None or supplier is None:
            raise ConflictError("Заказ или поставщик закупки не найден.")

        items = approval.payload.get("items") or []
        try:
            result = await SupplierService(self.db).adapter_for(supplier).order(
                data=SupplierOrderData(
                    order_number=order.order_number,
                    items=items,
                    delivery_days=self._delivery_days(items),
                )
            )
        except SupplierAdapterError as exc:
            raise ConflictError(str(exc)) from exc

        approval.status = ApprovalStatus.approved
        approval.approved_by_user_id = user.id
        approval.approved_at = _now()

        action = self.db.get(AgentAction, approval.action_id) if approval.action_id else None
        if action is not None:
            action.status = AgentActionStatus.executed
            action.executed_at = _now()
            action.result_data = {
                "external_order_id": result.external_order_id,
                "supplier_status": result.status,
            }

        self._stamp_fulfillments(order, supplier, result)

        if order.status == OrderStatus.new:
            order.status = OrderStatus.confirmed
            order.confirmed_at = _now()

        # The purchase is now placed: the supplier accepted the order, so the
        # tracking lifecycle starts at "accepted".
        self.compute_tracking_status(order)

        AuditService(self.db).record(
            action="supplier_order.approve",
            entity_type="order",
            entity_id=str(order.id),
            company_id=order.company_id,
            user_id=user.id,
            detail={
                "approval_id": str(approval.id),
                "supplier_id": str(supplier.id),
                "external_order_id": result.external_order_id,
                "order_number": order.order_number,
            },
        )
        self.db.commit()
        return {
            "approval_id": str(approval.id),
            "status": ApprovalStatus.approved.value,
            "already_approved": False,
            "external_order_id": result.external_order_id,
            "supplier_status": result.status,
            "order_status": order.status.value,
            "tracking_status": order.tracking_status,
            "order_id": str(order.id),
        }

    def reject_purchase(
        self,
        approval_id: uuid.UUID,
        user,
        reason: str = "",
    ) -> dict[str, Any]:
        """Reject a supplier purchase — no external order is placed."""
        approval = self._get_approval_or_raise(approval_id, user)
        self._require_manager(user)
        self._ensure_order_action(approval)

        if self._is_expired(approval):
            approval.status = ApprovalStatus.expired
            self.db.commit()
            raise ConflictError("Срок согласования истёк.")

        if approval.status == ApprovalStatus.rejected:
            return {
                "approval_id": str(approval.id),
                "status": ApprovalStatus.rejected.value,
                "already_rejected": True,
            }
        if approval.status != ApprovalStatus.pending:
            raise ConflictError(f"Запрос уже обработан (статус {approval.status.value}).")

        approval.status = ApprovalStatus.rejected
        approval.rejected_by_user_id = user.id
        approval.rejected_at = _now()
        approval.rejection_reason = reason or None

        action = self.db.get(AgentAction, approval.action_id) if approval.action_id else None
        if action is not None:
            action.status = AgentActionStatus.cancelled

        order_id = (approval.payload or {}).get("order_id")
        AuditService(self.db).record(
            action="supplier_order.reject",
            entity_type="order",
            entity_id=order_id or str(approval.id),
            company_id=approval.company_id,
            user_id=user.id,
            detail={"reason": reason or None},
        )
        self.db.commit()
        return {
            "approval_id": str(approval.id),
            "status": ApprovalStatus.rejected.value,
            "already_rejected": False,
        }

    # --- Tracking (Sprint 4.6) ---------------------------------------------

    def compute_tracking_status(self, order: Order) -> str:
        """Recompute the order's aggregate supplier-side milestone.

        The most advanced supplier line wins; ``handed_over`` is a manager
        decision and is never downgraded by a recompute.
        """
        if order.tracking_status == TrackingStatus.handed_over.value:
            return order.tracking_status
        rank = 0
        for fulfillment in self._fulfillments(order.id):
            if not fulfillment.external_order_id or not fulfillment.supplier_status:
                continue
            rank = max(rank, _SUPPLIER_TO_RANK.get(fulfillment.supplier_status, 0))
        order.tracking_status = _TRACKING_ORDER[rank]
        return order.tracking_status

    async def refresh_tracking(
        self,
        order_id: uuid.UUID,
        *,
        notify: bool = True,
    ) -> dict[str, Any]:
        """Poll every supplier adapter and update the order's tracking.

        The agent "watches" the order here: for each placed line it asks the
        supplier adapter for the current status, stamps it on the fulfillment,
        recomputes the aggregate and — when the order just arrived — raises the
        customer notification ("Ваш заказ прибыл") through the approval flow.
        Best-effort: an unresponsive adapter never breaks tracking.
        """
        order = self.db.get(Order, order_id)
        if order is None:
            raise NotFoundError("Заказ не найден.")

        lines_by_supplier: dict[uuid.UUID, list[SupplierFulfillment]] = {}
        for fulfillment in self._fulfillments(order.id):
            if fulfillment.external_order_id:
                lines_by_supplier.setdefault(fulfillment.supplier_id, []).append(
                    fulfillment
                )
        for supplier_id, lines in lines_by_supplier.items():
            supplier = self.db.get(Supplier, supplier_id)
            if supplier is None or not supplier.is_active:
                continue
            adapter = SupplierService(self.db).adapter_for(supplier)
            for fulfillment in lines:
                try:
                    status = await adapter.order_status(fulfillment.external_order_id)
                except SupplierAdapterError:
                    continue
                if status and status != "unknown":
                    fulfillment.supplier_status = status
        self.db.flush()

        previous = order.tracking_status
        current = self.compute_tracking_status(order)
        self.db.flush()

        notification = None
        if (
            notify
            and current == TrackingStatus.arrived.value
            and previous != TrackingStatus.arrived.value
        ):
            notification = self._maybe_notify_arrived(order)

        self.db.commit()
        return self._tracking_info(order, notification=notification)

    def mark_handed_over(self, order_id: uuid.UUID, user) -> dict[str, Any]:
        """A manager confirms the order was handed to the customer."""
        order = self.db.get(Order, order_id)
        if order is None:
            raise NotFoundError("Заказ не найден.")
        if not company_allowed(user, order.company_id):
            raise ForbiddenError("Заказ принадлежит другой компании.")
        self._require_manager(user)
        if order.tracking_status == TrackingStatus.handed_over.value:
            return {
                "order_id": str(order.id),
                "order_number": order.order_number,
                "tracking_status": TrackingStatus.handed_over.value,
                "already_handed_over": True,
            }
        if order.tracking_status != TrackingStatus.arrived.value:
            raise ConflictError("Заказ ещё не прибыл — выдача недоступна.")
        order.tracking_status = TrackingStatus.handed_over.value
        AuditService(self.db).record(
            action="order.hand_over",
            entity_type="order",
            entity_id=str(order.id),
            company_id=order.company_id,
            user_id=user.id,
            detail={"order_number": order.order_number},
        )
        self.db.commit()
        return {
            "order_id": str(order.id),
            "order_number": order.order_number,
            "tracking_status": TrackingStatus.handed_over.value,
            "already_handed_over": False,
        }

    def _maybe_notify_arrived(self, order: Order) -> dict[str, Any] | None:
        """Raise the "Ваш заказ прибыл" customer notification (once).

        Goes through the PermissionEngine: on LOW the agent informs the
        customer on its own; otherwise an ApprovalRequest is created and a
        manager decides. Idempotent via the ``order_arrived:{id}`` action key.
        """
        key = f"order_arrived:{order.id}"
        existing = self._find_action_by_key(order.company_id, key)
        if existing is not None:
            pending = self._approval_for_action(existing.id)
            if existing.status == AgentActionStatus.executed:
                return {
                    "kind": "arrival",
                    "status": "sent",
                    "message_sent": True,
                    "already_sent": True,
                }
            if pending is not None:
                return {
                    "kind": "arrival",
                    "status": pending.status.value,
                    "approval_id": str(pending.id),
                    "message_sent": False,
                    "already_sent": False,
                }
            return {
                "kind": "arrival",
                "status": "pending",
                "message_sent": False,
                "already_sent": False,
            }

        message = (
            f"Ваш заказ {order.order_number} прибыл в автосервис и готов к выдаче. "
            "Ждём вас!"
        )
        decision = permissions.evaluate(
            agent=None,
            company=self.db.get(Company, order.company_id),
            action="send_customer_message",
            resource=None,
            context={"order_id": str(order.id)},
        )
        risk = ApprovalRiskLevel(decision.risk_level)
        if decision.requires_approval:
            action = AgentAction(
                company_id=order.company_id,
                agent_id=None,
                action_type="send_customer_message",
                target_type="order",
                target_id=str(order.id),
                input_data={"order_id": str(order.id), "kind": "order_notification"},
                risk_level=risk,
                requires_approval=True,
                status=AgentActionStatus.pending,
                idempotency_key=key,
            )
            self.db.add(action)
            self.db.flush()
            approval = ApprovalRequest(
                company_id=order.company_id,
                conversation_id=order.conversation_id,
                quote_id=order.quote_id,
                action_id=action.id,
                action_type="send_customer_message",
                status=ApprovalStatus.pending,
                payload={
                    "kind": "order_notification",
                    "order_id": str(order.id),
                    "message": message,
                    "conversation_id": str(order.conversation_id),
                },
                risk_level=risk,
                requested_by_agent_id=None,
                expires_at=_now() + timedelta(hours=settings.approval_ttl_hours),
            )
            self.db.add(approval)
            self.db.flush()
            return {
                "kind": "arrival",
                "status": ApprovalStatus.pending.value,
                "approval_id": str(approval.id),
                "message_sent": False,
                "already_sent": False,
            }

        # LOW risk — the agent acts alone.
        conversation = (
            self.db.get(Conversation, order.conversation_id)
            if order.conversation_id
            else None
        )
        if conversation is None:
            return None
        from app.services.conversation_service import ConversationService

        msg, _ = ConversationService(self.db).add_message(
            conversation,
            content=message,
            sender_type="agent",
            sender_id=None,
            structured_data={
                "kind": "order_notification",
                "order_id": str(order.id),
            },
        )
        self.db.add(
            AgentAction(
                company_id=order.company_id,
                agent_id=None,
                action_type="send_customer_message",
                target_type="order",
                target_id=str(order.id),
                input_data={"order_id": str(order.id), "kind": "order_notification"},
                risk_level=risk,
                requires_approval=False,
                status=AgentActionStatus.executed,
                idempotency_key=key,
                result_data={"message_id": str(msg.id), "order_id": str(order.id)},
                executed_at=_now(),
            )
        )
        self.db.flush()
        return {
            "kind": "arrival",
            "status": "sent",
            "message_id": str(msg.id),
            "message_sent": True,
            "already_sent": False,
        }

    def _tracking_info(
        self,
        order: Order,
        notification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        suppliers: list[dict[str, Any]] = []
        seen: set[uuid.UUID] = set()
        for fulfillment in self._fulfillments(order.id):
            if fulfillment.supplier_id in seen:
                continue
            seen.add(fulfillment.supplier_id)
            supplier = self.db.get(Supplier, fulfillment.supplier_id)
            suppliers.append(
                {
                    "supplier_id": str(fulfillment.supplier_id),
                    "supplier_name": supplier.name if supplier is not None else "",
                    "external_order_id": fulfillment.external_order_id,
                    "supplier_status": fulfillment.supplier_status,
                }
            )
        return {
            "order_id": str(order.id),
            "order_number": order.order_number,
            "order_status": order.status.value,
            "tracking_status": order.tracking_status,
            "suppliers": suppliers,
            "notification": notification,
        }

    # --- Read models --------------------------------------------------------

    def list_purchases(
        self,
        *,
        company_id: uuid.UUID | None = None,
        order_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(ApprovalRequest)
            .where(ApprovalRequest.action_type == _ORDER_ACTION)
            .order_by(ApprovalRequest.created_at.desc())
        )
        if company_id:
            stmt = stmt.where(ApprovalRequest.company_id == company_id)
        approvals = list(self.db.scalars(stmt.limit(limit)).unique().all())
        result = []
        for approval in approvals:
            payload = approval.payload or {}
            if order_id is not None and payload.get("order_id") != str(order_id):
                continue
            result.append(self._read(approval))
        return result

    def get_purchase(self, approval_id: uuid.UUID) -> dict[str, Any] | None:
        approval = self.db.get(ApprovalRequest, approval_id)
        if approval is None or approval.action_type != _ORDER_ACTION:
            return None
        return self._read(approval)

    # --- Internals ----------------------------------------------------------

    def _read(self, approval: ApprovalRequest) -> dict[str, Any]:
        payload = approval.payload or {}
        supplier = None
        supplier_id = payload.get("supplier_id")
        if supplier_id:
            supplier = self.db.get(Supplier, uuid.UUID(str(supplier_id)))
        fulfillments = self._fulfillments_for(
            payload.get("order_id"), payload.get("supplier_id")
        )
        external = next(
            (f.external_order_id for f in fulfillments if f.external_order_id),
            None,
        )
        status = next(
            (f.supplier_status for f in fulfillments if f.supplier_status),
            None,
        )
        order = None
        order_id = payload.get("order_id")
        if order_id:
            order = self.db.get(Order, uuid.UUID(str(order_id)))
            if order is not None:
                self.compute_tracking_status(order)
        return {
            "approval_id": str(approval.id),
            "order_id": payload.get("order_id"),
            "order_number": order.order_number if order is not None else None,
            "supplier_id": payload.get("supplier_id"),
            "supplier_name": supplier.name if supplier is not None else "",
            "action_type": approval.action_type,
            "status": approval.status.value,
            "risk_level": approval.risk_level.value,
            "external_order_id": external,
            "supplier_status": status,
            "order_status": order.status.value if order is not None else None,
            "tracking_status": (
                order.tracking_status if order is not None else None
            ),
            "items": payload.get("items") or [],
            "order_total": payload.get("order_total"),
            "created_at": approval.created_at,
            "approved_at": approval.approved_at,
            "rejected_at": approval.rejected_at,
            "rejection_reason": approval.rejection_reason,
            "expires_at": approval.expires_at,
        }

    def _supplier_groups(self, order: Order) -> list[tuple[uuid.UUID, list[dict[str, Any]]]]:
        """Group the order lines by supplier, enriching with offer facts."""
        offer_ids = [
            uuid.UUID(str(item.get("offer_id")))
            for item in (order.items or [])
            if item.get("offer_id")
        ]
        offers: dict[str, SupplierOffer] = {}
        if offer_ids:
            offers = {
                str(o.id): o
                for o in self.db.scalars(
                    select(SupplierOffer).where(SupplierOffer.id.in_(offer_ids))
                ).unique()
            }
        groups: dict[str, dict[str, Any]] = {}
        for item in order.items or []:
            offer = offers.get(str(item.get("offer_id")))
            if offer is None or offer.supplier_id is None:
                continue
            supplier_id = str(offer.supplier_id)
            line = {
                "article": str(item.get("article") or "").strip(),
                "brand": str(item.get("brand") or "").strip() or offer.brand,
                "part_name": str(item.get("part_name") or "").strip(),
                "quantity": _item_int(item, "quantity_available")
                or _item_int(item, "quantity"),
                "purchase_price": (
                    str(offer.purchase_price) if offer.purchase_price is not None else None
                ),
                "delivery_days": offer.delivery_days,
                "offer_id": str(offer.id),
            }
            group = groups.setdefault(
                supplier_id,
                {"supplier_id": uuid.UUID(supplier_id), "items": []},
            )
            group["items"].append(line)
        return [(g["supplier_id"], g["items"]) for g in groups.values()]

    def _stamp_fulfillments(
        self,
        order: Order,
        supplier: Supplier,
        result: Any,
    ) -> None:
        fulfillments = list(
            self.db.scalars(
                select(SupplierFulfillment).where(
                    SupplierFulfillment.order_id == order.id,
                    SupplierFulfillment.supplier_id == supplier.id,
                )
            ).unique()
        )
        for fulfillment in fulfillments:
            fulfillment.external_order_id = result.external_order_id
            fulfillment.supplier_status = result.status
            fulfillment.ordered_at = _now()

    @staticmethod
    def _delivery_days(items: list[dict[str, Any]]) -> int | None:
        days = [
            int(it.get("delivery_days"))
            for it in items
            if it.get("delivery_days") is not None
        ]
        return max(days) if days else None

    def _fulfillments_for(self, order_id: Any, supplier_id: Any) -> list[SupplierFulfillment]:
        if not order_id or not supplier_id:
            return []
        return list(
            self.db.scalars(
                select(SupplierFulfillment).where(
                    SupplierFulfillment.order_id == uuid.UUID(str(order_id)),
                    SupplierFulfillment.supplier_id == uuid.UUID(str(supplier_id)),
                )
            ).unique()
        )

    def _fulfillments(self, order_id: Any) -> list[SupplierFulfillment]:
        if not order_id:
            return []
        return list(
            self.db.scalars(
                select(SupplierFulfillment).where(
                    SupplierFulfillment.order_id == uuid.UUID(str(order_id))
                )
            ).unique()
        )

    def _external_order_id(self, approval: ApprovalRequest) -> str | None:
        payload = approval.payload or {}
        fulfillments = self._fulfillments_for(
            payload.get("order_id"), payload.get("supplier_id")
        )
        return next((f.external_order_id for f in fulfillments if f.external_order_id), None)

    def _order_status(self, approval: ApprovalRequest) -> str | None:
        order_id = (approval.payload or {}).get("order_id")
        if not order_id:
            return None
        order = self.db.get(Order, uuid.UUID(str(order_id)))
        return order.status.value if order is not None else None

    def _get_approval_or_raise(self, approval_id: uuid.UUID, user) -> ApprovalRequest:
        approval = self.db.get(ApprovalRequest, approval_id)
        if approval is None:
            raise NotFoundError("Запрос на согласование не найден.")
        if not company_allowed(user, approval.company_id):
            raise ForbiddenError("Запрос принадлежит другой компании.")
        return approval

    @staticmethod
    def _require_manager(user) -> None:
        if user is None or not user.is_superuser:
            raise ForbiddenError(
                "Закупка у поставщика — действие высокого риска, доступно только менеджеру."
            )

    @staticmethod
    def _ensure_order_action(approval: ApprovalRequest) -> None:
        if approval.action_type != _ORDER_ACTION:
            raise ConflictError(
                "Этот запрос не относится к закупке у поставщика."
            )

    @staticmethod
    def _is_expired(approval: ApprovalRequest) -> bool:
        expires_at = approval.expires_at
        if expires_at is None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return _now() > expires_at

    def _find_action_by_key(self, company_id: uuid.UUID, key: str) -> AgentAction | None:
        stmt = (
            select(AgentAction)
            .where(AgentAction.company_id == company_id)
            .where(AgentAction.idempotency_key == key)
            .order_by(AgentAction.created_at.desc())
        )
        return self.db.scalars(stmt).first()

    def _approval_for_action(self, action_id: uuid.UUID | None) -> ApprovalRequest | None:
        if action_id is None:
            return None
        stmt = select(ApprovalRequest).where(ApprovalRequest.action_id == action_id)
        return self.db.scalars(stmt).first()


def _item_int(item: dict[str, Any], key: str) -> int | None:
    value = item.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
