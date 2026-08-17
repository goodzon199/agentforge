from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.access import ensure_writer
from app.api.deps import get_current_user, get_order_service, get_sales_service
from app.models import Quote, User
from app.schemas.orders import OrderCreateResult, QuoteAcceptResult
from app.schemas.sales import (
    QuotePrepareIn,
    QuoteRejectIn,
    QuoteSendIn,
    QuoteSendResult,
    SalesDraftRead,
)
from app.services.order_service import OrderService
from app.services.sales_service import (
    ConflictError,
    ForbiddenError,
    GuardBlockedError,
    SalesService,
    company_allowed,
)

router = APIRouter(prefix="/quotes", tags=["quotes"])


def _load_quote(quote_id: uuid.UUID, service: SalesService, user: User) -> Quote:
    quote = service.db.get(Quote, quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="Квота не найдена")
    if not company_allowed(user, quote.company_id):
        raise HTTPException(status_code=403, detail="Квота принадлежит другой компании")
    return quote


def _draft(service: SalesService, quote: Quote) -> SalesDraftRead:
    return SalesDraftRead(**service.sales_draft_info(quote))


@router.get("/{quote_id}/sales-draft", response_model=SalesDraftRead)
def get_sales_draft(
    quote_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    quote = _load_quote(quote_id, service, user)
    return _draft(service, quote)


@router.post("/{quote_id}/prepare", response_model=SalesDraftRead)
def prepare_sales_draft(
    quote_id: uuid.UUID,
    payload: QuotePrepareIn,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    quote = _load_quote(quote_id, service, user)
    ensure_writer(user)
    if payload.message is not None:
        service.save_edited(quote, payload.message)
        service.db.commit()
    elif quote.ai_draft is None:
        from app.llm.client import llm_client

        service.generate_draft(quote, llm=llm_client)
        service.db.commit()
    return _draft(service, quote)


@router.post("/{quote_id}/send", response_model=QuoteSendResult)
def send_quote(
    quote_id: uuid.UUID,
    payload: QuoteSendIn,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    quote = _load_quote(quote_id, service, user)
    ensure_writer(user)
    try:
        result = service.request_send(
            quote, payload.message, user, approve_now=payload.approve_now
        )
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GuardBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"guard": exc.guard},
        ) from exc
    return QuoteSendResult(**result)


@router.post("/{quote_id}/reject", response_model=SalesDraftRead)
def reject_quote(
    quote_id: uuid.UUID,
    payload: QuoteRejectIn,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    quote = _load_quote(quote_id, service, user)
    ensure_writer(user)
    try:
        service.quote_reject(quote, user, payload.reason)
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _draft(service, quote)


@router.post("/{quote_id}/accept", response_model=QuoteAcceptResult)
def accept_quote(
    quote_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
    orders: OrderService = Depends(get_order_service),
):
    quote = _load_quote(quote_id, service, user)
    ensure_writer(user)
    try:
        result = orders.accept(quote, user)
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return QuoteAcceptResult(**result)


@router.post("/{quote_id}/convert", response_model=OrderCreateResult)
def convert_quote_to_order(
    quote_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
    orders: OrderService = Depends(get_order_service),
):
    quote = _load_quote(quote_id, service, user)
    ensure_writer(user)
    try:
        result = orders.create_from_quote(quote, user)
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OrderCreateResult(**result)
