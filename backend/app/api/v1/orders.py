from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_order_service
from app.models import User
from app.schemas.orders import OrderRead
from app.services.order_service import OrderService
from app.services.sales_service import company_allowed

router = APIRouter(prefix="/orders", tags=["orders"])


def _read(order) -> OrderRead:
    return OrderRead(
        id=order.id,
        company_id=order.company_id,
        conversation_id=order.conversation_id,
        customer_id=order.customer_id,
        part_request_id=order.part_request_id,
        quote_id=order.quote_id,
        order_number=order.order_number,
        status=order.status.value,
        currency=order.currency,
        order_total=str(order.order_total) if order.order_total is not None else None,
        items=order.items or [],
        created_by_user_id=order.created_by_user_id,
        confirmed_at=order.confirmed_at,
        created_at=order.created_at,
    )


@router.get("", response_model=list[OrderRead])
def list_orders(
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return [_read(o) for o in service.list_orders(company_id=user.company_id)]


@router.get("/{order_id}", response_model=OrderRead)
def get_order(
    order_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    order = service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    if not company_allowed(user, order.company_id):
        raise HTTPException(status_code=403, detail="Заказ принадлежит другой компании")
    return _read(order)
