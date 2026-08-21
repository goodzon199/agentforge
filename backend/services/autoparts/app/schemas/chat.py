from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class PublicChatStart(BaseModel):
    """Entry point of the public web-chat widget (no JWT).

    public_token identifies the company; client_key lets the widget resume
    its previous conversation on the same device.
    """

    public_token: str = Field(min_length=1, max_length=64)
    visitor_name: str = Field(default="Гость", max_length=180)
    client_key: str = Field(default="", max_length=120)


class PublicChatStarted(BaseModel):
    conversation_id: uuid.UUID
    customer_id: uuid.UUID
    company_id: uuid.UUID
    visitor_name: str
    client_key: str
    channel: str = "webchat"
    mode: str
    status: str


class PublicChatMessageIn(BaseModel):
    conversation_id: uuid.UUID
    content: str = Field(min_length=1, max_length=4000)


class PublicChatMessageRead(ORMModel):
    id: uuid.UUID
    sender_type: str
    content: str
    created_at: datetime


class PublicChatMessages(BaseModel):
    conversation_id: uuid.UUID
    mode: str
    status: str
    messages: list[PublicChatMessageRead]


class PublicChatSent(BaseModel):
    message: PublicChatMessageRead
    task_id: uuid.UUID | None = None
