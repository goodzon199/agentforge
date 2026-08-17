from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SupplierPurchaseRequestIn(BaseModel):
    order_id: uuid.UUID


class SupplierPurchaseRead(BaseModel):
    """One purchase request (ApprovalRequest of type send_supplier_order)."""

    approval_id: uuid.UUID
    order_id: str | None = None
    order_number: str | None = None
    supplier_id: str | None = None
    supplier_name: str = ""
    action_type: str
    status: str
    risk_level: str
    external_order_id: str | None = None
    supplier_status: str | None = None
    order_status: str | None = None
    tracking_status: str | None = None
    items: list[dict[str, Any]] = []
    order_total: str | None = None
    created_at: datetime
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    expires_at: datetime | None = None


class SupplierTrackingSupplier(BaseModel):
    supplier_id: str
    supplier_name: str = ""
    external_order_id: str | None = None
    supplier_status: str | None = None


class SupplierTrackingRead(BaseModel):
    """The live supplier-side lifecycle of an order (Sprint 4.6)."""

    order_id: uuid.UUID
    order_number: str
    order_status: str
    tracking_status: str
    suppliers: list[SupplierTrackingSupplier] = []
    notification: dict[str, Any] | None = None


class SupplierHandOverResult(BaseModel):
    order_id: uuid.UUID
    order_number: str
    tracking_status: str
    already_handed_over: bool = False


class SupplierPurchaseResult(BaseModel):
    approval_id: uuid.UUID | None = None
    status: str
    already_approved: bool = False
    already_rejected: bool = False
    already_executed: bool = False
    external_order_id: str | None = None
    supplier_status: str | None = None
    order_status: str | None = None
    tracking_status: str | None = None
    order_id: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
