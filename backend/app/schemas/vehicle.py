from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class VehicleRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    customer_id: uuid.UUID
    vin: str
    brand: str
    model: str
    year: int | None
    engine: str
    body: str
    registration_number: str
    created_at: datetime
    updated_at: datetime


class VehicleUpdate(BaseModel):
    vin: str | None = None
    brand: str | None = None
    model: str | None = None
    year: int | None = None
    engine: str | None = None
    body: str | None = None
    registration_number: str | None = None
