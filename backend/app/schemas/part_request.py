from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
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


class SupplierOfferRead(BaseModel):
    """A normalized supplier offer. ``purchase_price`` is manager/pricing-only."""

    id: uuid.UUID
    part_request_id: uuid.UUID
    search_run_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str = ""
    brand: str
    article: str
    part_name: str
    purchase_price: Decimal | None = None
    quantity: int | None = None
    delivery_days: int | None = None
    customer_price: Decimal | None = None
    total_price: Decimal | None = None
    margin_percent: Decimal | None = None
    created_at: datetime


class SupplierAttemptRead(BaseModel):
    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str = ""
    status: str
    offers_found: int
    error: str = ""
    latency_ms: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class SupplierSearchRunRead(BaseModel):
    id: uuid.UUID
    part_request_id: uuid.UUID
    status: str
    offers_found: int
    suppliers_succeeded: int
    suppliers_failed: int
    error: str = ""
    structured_data: dict[str, Any] = {}
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    attempts: list[SupplierAttemptRead] = []


class PartSearchResult(BaseModel):
    run_id: uuid.UUID
    part_request_id: uuid.UUID
    status: str
    offers_found: int
    suppliers_succeeded: int
    suppliers_failed: int
    next_action: str = "pricing_parts"


class PartQuoteRead(BaseModel):
    """The pricing-engine result for a part request (stored quote)."""

    status: str
    part_request_id: uuid.UUID
    run_id: uuid.UUID | None = None
    triggered_by: str = ""
    margin_percent: float | None = None
    currency: str = "RUB"
    offers_total: int = 0
    offers_priced: int = 0
    quantity: int = 1
    best_offer_id: uuid.UUID | None = None
    best_brand: str = ""
    best_article: str = ""
    best_part_name: str = ""
    best_unit_price: Decimal | None = None
    best_total_price: Decimal | None = None
    priced_at: datetime | None = None

