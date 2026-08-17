from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SupplierCreate(BaseModel):
    company_id: uuid.UUID
    name: str = Field(min_length=1, max_length=180)
    adapter_type: str = Field(default="mock", max_length=40)
    is_active: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    adapter_type: str | None = Field(default=None, max_length=40)
    is_active: bool | None = None
    settings: dict[str, Any] | None = None


class SupplierRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    slug: str
    adapter_type: str
    is_active: bool
    settings: dict[str, Any]
    is_experimental: bool = False
    created_at: datetime
    updated_at: datetime


class SupplierTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
    offers_found: int = 0


# --- Sprint 4.2 — Supplier Intelligence ----------------------------------


class SupplierReliabilityRead(BaseModel):
    """The live scoreboard the system computes for a supplier."""

    supplier_id: uuid.UUID
    supplier_name: str
    rating: float
    rating_source: str
    rating_version: str
    computed_at: datetime

    orders_total: int
    confirmed: int
    cancelled: int
    confirmation_rate: float | None
    cancellation_rate: float | None

    fulfillments_total: int
    fulfillments_recorded: int
    on_time_delivery: float | None
    price_change_rate: float | None
    under_delivery_rate: float | None

    returns_total: int
    return_rate: float | None

    attempts_total: int
    attempts_failed: int
    api_availability: float | None
    api_avg_latency_ms: float | None
    api_p95_latency_ms: float | None

    reliability_score: float
    api_score: float


class FulfillmentRecord(BaseModel):
    """Manager records what actually happened on an order line."""

    fulfillment_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    article: str | None = None
    actual_purchase_price: Decimal | None = None
    actual_delivery_days: int | None = None
    quantity_delivered: int | None = None
    status: str = Field(default="delivered", max_length=20)
    delivered_at: datetime | None = None


class SupplierFulfillmentRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    supplier_id: uuid.UUID
    order_id: uuid.UUID | None
    offer_id: uuid.UUID | None
    article: str
    brand: str
    promised_purchase_price: Decimal | None
    promised_delivery_days: int | None
    quantity_ordered: int | None
    actual_purchase_price: Decimal | None
    actual_delivery_days: int | None
    quantity_delivered: int | None
    status: str
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime

