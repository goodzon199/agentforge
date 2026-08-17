from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.access import ensure_writer
from app.api.deps import get_current_user, get_order_service, get_supplier_order_service
from app.models import Order, User
from app.schemas.sales import ApprovalRejectIn
from app.schemas.supplier_orders import (
    SupplierHandOverResult,
    SupplierPurchaseRead,
    SupplierPurchaseRequestIn,
    SupplierPurchaseResult,
    SupplierTrackingRead,
)
from app.services.order_service import OrderService
from app.services.sales_service import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    company_allowed,
)
from app.services.supplier_order_service import SupplierOrderService

router = APIRouter(prefix="/supplier-orders", tags=["supplier-orders"])


@router.get("", response_model=list[SupplierPurchaseRead])
def list_purchases(
    order_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    service: SupplierOrderService = Depends(get_supplier_order_service),
):
    return service.list_purchases(company_id=user.company_id, order_id=order_id)


@router.post("", response_model=list[SupplierPurchaseRead])
def request_purchases(
    payload: SupplierPurchaseRequestIn,
    user: User = Depends(get_current_user),
    orders: OrderService = Depends(get_order_service),
    service: SupplierOrderService = Depends(get_supplier_order_service),
):
    """Ask to purchase the order's parts (idempotent, HIGH risk).

    Normally this fires automatically when the order is created from an
    accepted quote; this endpoint lets a manager (re)trigger it or create the
    request retroactively for an order converted before 4.5.
    """
    order = orders.get_order(payload.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if not company_allowed(user, order.company_id):
        raise HTTPException(status_code=403, detail="Заказ принадлежит другой компании")
    ensure_writer(user)
    service.request_purchase(order)
    service.db.commit()
    return service.list_purchases(company_id=user.company_id, order_id=order.id)


@router.post("/{order_id}/track", response_model=SupplierTrackingRead)
async def track_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SupplierOrderService = Depends(get_supplier_order_service),
):
    """Poll the supplier adapters and refresh the order's tracking status.

    Drives the self-tracking loop: when a purchase has just arrived, this also
    raises the customer notification ("Ваш заказ прибыл").
    """
    order = service.db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if not company_allowed(user, order.company_id):
        raise HTTPException(status_code=403, detail="Заказ принадлежит другой компании")
    ensure_writer(user)
    try:
        return await service.refresh_tracking(order_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{order_id}/hand-over", response_model=SupplierHandOverResult)
def hand_over_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SupplierOrderService = Depends(get_supplier_order_service),
):
    """A manager confirms the arrived order was handed to the customer."""
    ensure_writer(user)
    try:
        return service.mark_handed_over(order_id, user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{approval_id}/approve", response_model=SupplierPurchaseResult)
async def approve_purchase(
    approval_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SupplierOrderService = Depends(get_supplier_order_service),
):
    """Approve the purchase — places the external order with the supplier."""
    ensure_writer(user)
    try:
        result = await service.approve_purchase(approval_id, user)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SupplierPurchaseResult(**result)


@router.post("/{approval_id}/reject", response_model=SupplierPurchaseResult)
def reject_purchase(
    approval_id: uuid.UUID,
    payload: ApprovalRejectIn,
    user: User = Depends(get_current_user),
    service: SupplierOrderService = Depends(get_supplier_order_service),
):
    """Reject the purchase — no external order is placed."""
    ensure_writer(user)
    try:
        result = service.reject_purchase(approval_id, user, payload.rejection_reason)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SupplierPurchaseResult(**result)
