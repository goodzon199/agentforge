from __future__ import annotations

import uuid
from datetime import datetime
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
    created_at: datetime
    updated_at: datetime


class SupplierTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int | None = None
    offers_found: int = 0
