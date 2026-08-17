from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PartRequest, Vehicle
from app.models.enums import PartRequestStatus

_ACTIVE_STATUSES = (
    PartRequestStatus.collecting_data,
    PartRequestStatus.ready_for_search,
)


class PartRequestService:
    """Owns the structured part requests and the customer's vehicles."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Part requests -----------------------------------------------------

    def list(
        self,
        *,
        company_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        status: PartRequestStatus | None = None,
        limit: int = 100,
    ) -> list[PartRequest]:
        stmt = select(PartRequest).order_by(PartRequest.created_at.desc())
        if company_id:
            stmt = stmt.where(PartRequest.company_id == company_id)
        if conversation_id:
            stmt = stmt.where(PartRequest.conversation_id == conversation_id)
        if status:
            stmt = stmt.where(PartRequest.status == status)
        return list(self.db.scalars(stmt.limit(limit)).unique().all())

    def get(self, part_request_id: uuid.UUID) -> PartRequest | None:
        return self.db.get(PartRequest, part_request_id)

    def get_active_for_conversation(
        self, conversation_id: uuid.UUID
    ) -> PartRequest | None:
        """The latest request still collecting data / waiting for search."""
        stmt = (
            select(PartRequest)
            .where(PartRequest.conversation_id == conversation_id)
            .where(PartRequest.status.in_(_ACTIVE_STATUSES))
            .order_by(PartRequest.created_at.desc())
        )
        return self.db.scalars(stmt).first()

    def find_by_source_message(self, message_id: uuid.UUID) -> PartRequest | None:
        stmt = select(PartRequest).where(PartRequest.source_message_id == message_id)
        return self.db.scalars(stmt).first()

    def create(
        self,
        *,
        company_id: uuid.UUID,
        conversation_id: uuid.UUID,
        customer_id: uuid.UUID,
        source_message_id: uuid.UUID | None,
        part_name: str = "",
        article: str = "",
        quantity: int = 1,
        vehicle_id: uuid.UUID | None = None,
        intent: str = "part_search",
        status: PartRequestStatus = PartRequestStatus.collecting_data,
        missing_fields: list[str] | None = None,
        structured_data: dict[str, Any] | None = None,
    ) -> PartRequest:
        part_request = PartRequest(
            company_id=company_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            source_message_id=source_message_id,
            vehicle_id=vehicle_id,
            part_name=part_name,
            article=article,
            quantity=quantity,
            intent=intent,
            status=status,
            missing_fields=missing_fields or [],
            structured_data=structured_data or {},
        )
        self.db.add(part_request)
        return part_request

    def update(self, part_request: PartRequest, **updates: Any) -> PartRequest:
        for key, value in updates.items():
            if hasattr(part_request, key) and key not in ("id", "company_id"):
                setattr(part_request, key, value)
        return part_request

    # --- Vehicles ----------------------------------------------------------

    def get_vehicle(self, vehicle_id: uuid.UUID) -> Vehicle | None:
        return self.db.get(Vehicle, vehicle_id)

    def find_vehicle(
        self,
        *,
        company_id: uuid.UUID,
        customer_id: uuid.UUID,
        vin: str = "",
        brand: str = "",
        model: str = "",
    ) -> Vehicle | None:
        stmt = (
            select(Vehicle)
            .where(Vehicle.company_id == company_id)
            .where(Vehicle.customer_id == customer_id)
        )
        if vin:
            stmt = stmt.where(Vehicle.vin == vin)
        elif brand and model:
            stmt = stmt.where(Vehicle.brand == brand).where(Vehicle.model == model)
        else:
            return None
        return self.db.scalars(stmt).first()

    def create_vehicle(
        self,
        *,
        company_id: uuid.UUID,
        customer_id: uuid.UUID,
        vin: str = "",
        brand: str = "",
        model: str = "",
        year: int | None = None,
        engine: str = "",
        body: str = "",
        registration_number: str = "",
    ) -> Vehicle:
        vehicle = Vehicle(
            company_id=company_id,
            customer_id=customer_id,
            vin=vin,
            brand=brand,
            model=model,
            year=year,
            engine=engine,
            body=body,
            registration_number=registration_number,
        )
        self.db.add(vehicle)
        return vehicle
