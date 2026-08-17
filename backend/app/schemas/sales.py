from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class QuoteItemRead(BaseModel):
    offer_id: str = ""
    brand: str
    article: str
    part_name: str = ""
    sale_price: str | None = None
    total_price: str | None = None
    delivery_days: int | None = None
    quantity_available: int | None = None
    margin_percent: str | None = None


class SalesDraftRead(BaseModel):
    quote_id: uuid.UUID
    part_request_id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    currency: str = "RUB"
    quote_total: str | None = None
    best_offer_id: uuid.UUID | None = None
    items: list[QuoteItemRead] = []
    ai_draft: str | None = None
    manager_edited: str | None = None
    final_message: str | None = None
    guard_status: str = "none"
    guard_errors: list[str] | None = None
    sent_at: datetime | None = None
    created_at: datetime | None = None


class QuotePrepareIn(BaseModel):
    message: str | None = None


class QuoteSendIn(BaseModel):
    message: str | None = None
    # Sprint 3.8.2 вЂ” Assist Mode: manager one-click send. When True the
    # approval is created and immediately approved by the same manager
    # (no second click).
    approve_now: bool = False


class QuoteRejectIn(BaseModel):
    reason: str = ""


class QuoteSendResult(BaseModel):
    approval_id: uuid.UUID | None = None
    status: str
    message_sent: bool = False
    already_executed: bool = False
    quote_id: uuid.UUID | None = None
    guard: dict[str, Any] | None = None
    # Sprint 3.8.3 вЂ” Controlled Auto: set when the quote went out without a
    # human (all safe conditions held).
    auto_sent: bool = False
    auto_reasons: list[str] | None = None


class ApprovalRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    task_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    quote_id: uuid.UUID | None = None
    action_id: uuid.UUID | None = None
    action_type: str
    status: str
    payload: dict[str, Any] | None = None
    risk_level: str
    requested_by_agent_id: uuid.UUID | None = None
    approved_by_user_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    rejected_by_user_id: uuid.UUID | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    expires_at: datetime | None = None


class ApprovalRejectIn(BaseModel):
    rejection_reason: str = ""


class ApprovalActionResult(BaseModel):
    approval_id: uuid.UUID
    status: str
    message_sent: bool = False
    message_id: uuid.UUID | None = None
    already_approved: bool = False
    already_rejected: bool = False


class AgentActionRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    action_type: str
    target_type: str | None = None
    target_id: str | None = None
    input_data: dict[str, Any] | None = None
    result_data: dict[str, Any] | None = None
    risk_level: str
    status: str
    requires_approval: bool = False
    idempotency_key: str | None = None
    created_at: datetime
    executed_at: datetime | None = None
