from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

# --- Customer --------------------------------------------------------------

class CustomerCreate(BaseModel):
    company_id: uuid.UUID
    name: str = Field(min_length=1, max_length=180)
    phone: str = Field(default="", max_length=40)
    email: str = Field(default="", max_length=255)
    source: str = Field(default="web", max_length=40)
    external_id: str = Field(default="", max_length=120)


class CustomerRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    phone: str
    email: str
    source: str
    external_id: str
    created_at: datetime


# --- Conversation ----------------------------------------------------------

class ConversationCreate(BaseModel):
    company_id: uuid.UUID
    customer_id: uuid.UUID
    channel: str = Field(default="web", max_length=40)
    status: str = Field(default="open", max_length=40)
    mode: str = Field(default="ai_active", max_length=40)


class ConversationRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    customer_id: uuid.UUID
    channel: str
    status: str
    mode: str
    assigned_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    customer_name: str = ""


class ConversationDetail(ConversationRead):
    messages: list[MessageRead] = Field(default_factory=list)


# --- Message ---------------------------------------------------------------

class MessageCreate(BaseModel):
    sender_type: str = Field(default="customer", max_length=20)
    sender_id: uuid.UUID | None = None
    content: str = Field(min_length=1)
    structured_data: dict[str, Any] = Field(default_factory=dict)


class MessageRead(ORMModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_type: str
    sender_id: uuid.UUID | None
    content: str
    structured_data: dict[str, Any]
    created_at: datetime
    task_id: uuid.UUID | None = None


class MessageSent(BaseModel):
    message: MessageRead
    task_id: uuid.UUID | None = None


ConversationDetail.model_rebuild()
