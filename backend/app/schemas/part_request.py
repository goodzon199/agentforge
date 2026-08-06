from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.vehicle import VehicleRead


class PartRequestRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    source_message_id: uuid.UUID | None
    intent: str
    part_name: str
    article: str
    quantity: int
    status: str
    missing_fields: list[str]
    structured_data: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    vehicle: VehicleRead | None = None
    customer_name: str = ""


class PartRequestUpdate(BaseModel):
    status: str | None = None
    part_name: str | None = None
    article: str | None = None
    quantity: int | None = None
    missing_fields: list[str] | None = None
