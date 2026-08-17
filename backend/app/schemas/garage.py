from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class VehicleCreate(BaseModel):
    vin: str = Field(default="", max_length=17)
    brand: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=120)
    year: int | None = None
    engine: str = Field(default="", max_length=80)
    body: str = Field(default="", max_length=80)
    registration_number: str = Field(default="", max_length=20)


class VehicleRead(BaseModel):
    id: uuid.UUID
    vin: str
    brand: str
    model: str
    year: int | None
    engine: str
    body: str
    registration_number: str


class GarageVehicle(BaseModel):
    vehicle: VehicleRead
    history: list[dict[str, Any]]


class CustomerGarageRead(BaseModel):
    customer_id: uuid.UUID
    memory: dict[str, Any]
    vehicles: list[GarageVehicle]


class CustomerMemoryRead(BaseModel):
    customer_id: uuid.UUID
    segment: str
    avg_check: float | None
    preferences: dict[str, Any]
    updated_at: str | None = None
    avg_check_updated_at: str | None = None
