from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.sales import QuoteItemRead


class OrderRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    part_request_id: uuid.UUID
    quote_id: uuid.UUID | None = None

    order_number: str
    status: str
    currency: str = "RUB"
    order_total: str | None = None
    items: list[QuoteItemRead] = []
    created_by_user_id: uuid.UUID | None = None
    confirmed_at: datetime | None = None
    created_at: datetime


class QuoteAcceptResult(BaseModel):
    quote_id: uuid.UUID
    status: str
    already_accepted: bool = False


class OrderCreateResult(BaseModel):
    order_id: uuid.UUID | None = None
    order_number: str | None = None
    quote_id: uuid.UUID
    status: str
    already_converted: bool = False
