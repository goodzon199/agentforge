from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_part_request_service
from app.models import PartRequest
from app.models.enums import PartRequestStatus
from app.schemas.part_request import PartRequestRead, PartRequestUpdate
from app.services.part_request_service import PartRequestService

router = APIRouter(prefix="/part_requests", tags=["part_requests"])


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
