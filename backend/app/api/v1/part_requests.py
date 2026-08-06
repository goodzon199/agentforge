from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_part_request_service,
    get_parts_search_service,
    get_pricing_service,
)
from app.models import PartRequest
from app.models.enums import PartRequestStatus
from app.schemas.part_request import (
    PartQuoteRead,
    PartRequestRead,
    PartRequestUpdate,
    PartSearchResult,
    SupplierAttemptRead,
    SupplierOfferRead,
    SupplierSearchRunRead,
)
from app.services.part_request_service import PartRequestService
from app.services.parts_search_service import PartsSearchService
from app.services.pricing_service import PricingService

router = APIRouter(prefix="/part_requests", tags=["part_requests"])


def _offer_read(offer) -> SupplierOfferRead:
    return SupplierOfferRead(
        id=offer.id,
        part_request_id=offer.part_request_id,
        search_run_id=offer.search_run_id,
        supplier_id=offer.supplier_id,
        supplier_name=offer.supplier.name if offer.supplier else "",
        brand=offer.brand,
        article=offer.article,
        part_name=offer.part_name,
        purchase_price=offer.purchase_price,
        quantity=offer.quantity,
        delivery_days=offer.delivery_days,
        customer_price=offer.customer_price,
        total_price=offer.total_price,
        margin_percent=offer.margin_percent,
        created_at=offer.created_at,
    )


def _attempt_read(attempt) -> SupplierAttemptRead:
    return SupplierAttemptRead(
        id=attempt.id,
        supplier_id=attempt.supplier_id,
        supplier_name=attempt.supplier.name if attempt.supplier else "",
        status=attempt.status.value,
        offers_found=attempt.offers_found,
        error=attempt.error,
        latency_ms=attempt.latency_ms,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
    )


def _run_read(run) -> SupplierSearchRunRead:
    return SupplierSearchRunRead(
        id=run.id,
        part_request_id=run.part_request_id,
        status=run.status.value,
        offers_found=run.offers_found,
        suppliers_succeeded=run.suppliers_succeeded,
        suppliers_failed=run.suppliers_failed,
        error=run.error,
        structured_data=run.structured_data,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        attempts=[_attempt_read(a) for a in run.attempts],
    )


def _read(part_request: PartRequest) -> PartRequestRead:
    vehicle = None
    if part_request.vehicle_id is not None and part_request.vehicle is not None:
        from app.schemas.vehicle import VehicleRead

        vehicle = VehicleRead.model_validate(part_request.vehicle)
    return PartRequestRead(
        id=part_request.id,
        company_id=part_request.company_id,
        conversation_id=part_request.conversation_id,
        customer_id=part_request.customer_id,
        vehicle_id=part_request.vehicle_id,
        source_message_id=part_request.source_message_id,
        intent=part_request.intent,
        part_name=part_request.part_name,
        article=part_request.article,
        quantity=part_request.quantity,
        status=part_request.status.value,
        missing_fields=part_request.missing_fields,
        structured_data=part_request.structured_data,
        created_at=part_request.created_at,
        updated_at=part_request.updated_at,
        vehicle=vehicle,
        customer_name=part_request.customer.name if part_request.customer else "",
    )


@router.get("", response_model=list[PartRequestRead])
def list_part_requests(
    conversation_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
    status: str | None = None,
    service: PartRequestService = Depends(get_part_request_service),
):
    status_enum = None
    if status:
        try:
            status_enum = PartRequestStatus(status)
        except ValueError:
            raise HTTPException(status_code=422, detail="Некорректный статус")
    requests = service.list(
        company_id=company_id,
        conversation_id=conversation_id,
        status=status_enum,
    )
    return [_read(pr) for pr in requests]


@router.get("/{part_request_id}", response_model=PartRequestRead)
def get_part_request(
    part_request_id: uuid.UUID,
    service: PartRequestService = Depends(get_part_request_service),
):
    part_request = service.get(part_request_id)
    if part_request is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return _read(part_request)


@router.patch("/{part_request_id}", response_model=PartRequestRead)
def update_part_request(
    part_request_id: uuid.UUID,
    payload: PartRequestUpdate,
    service: PartRequestService = Depends(get_part_request_service),
):
    part_request = service.get(part_request_id)
    if part_request is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is not None:
        try:
            updates["status"] = PartRequestStatus(updates["status"])
        except ValueError:
            raise HTTPException(status_code=422, detail="Некорректный статус")
    service.update(part_request, **updates)
    service.db.commit()
    service.db.refresh(part_request)
    return _read(part_request)


# --- Supplier search --------------------------------------------------------


@router.get("/{part_request_id}/offers", response_model=list[SupplierOfferRead])
def list_offers(
    part_request_id: uuid.UUID,
    service: PartsSearchService = Depends(get_parts_search_service),
):
    if service.db.get(PartRequest, part_request_id) is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return [_offer_read(o) for o in service.list_offers(part_request_id)]


@router.post("/{part_request_id}/search", response_model=PartSearchResult)
def run_search(
    part_request_id: uuid.UUID,
    part_service: PartRequestService = Depends(get_part_request_service),
    search_service: PartsSearchService = Depends(get_parts_search_service),
):
    part_request = part_service.get(part_request_id)
    if part_request is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    result = search_service.search(part_request, triggered_by="user")
    return PartSearchResult(**result)


@router.get(
    "/{part_request_id}/search-runs", response_model=list[SupplierSearchRunRead]
)
def list_search_runs(
    part_request_id: uuid.UUID,
    service: PartsSearchService = Depends(get_parts_search_service),
):
    if service.db.get(PartRequest, part_request_id) is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    return [_run_read(r) for r in service.list_runs(part_request_id)]


# --- Pricing engine ---------------------------------------------------------


@router.post("/{part_request_id}/price", response_model=PartQuoteRead)
def run_pricing(
    part_request_id: uuid.UUID,
    part_service: PartRequestService = Depends(get_part_request_service),
    pricing_service: PricingService = Depends(get_pricing_service),
):
    if part_service.get(part_request_id) is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    summary = pricing_service.process(part_request_id, triggered_by="user")
    return PartQuoteRead(**summary)


@router.get("/{part_request_id}/quote", response_model=PartQuoteRead)
def get_quote(
    part_request_id: uuid.UUID,
    part_service: PartRequestService = Depends(get_part_request_service),
    pricing_service: PricingService = Depends(get_pricing_service),
):
    if part_service.get(part_request_id) is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    summary = pricing_service.summary(part_request_id)
    return PartQuoteRead(**summary)
