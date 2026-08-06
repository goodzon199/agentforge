from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, ConversationMessage, Customer
from app.services.task_service import TaskService


class ConversationService:
    """Owns customers, conversations and their messages."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Customers ---------------------------------------------------------

    def create_customer(
        self,
        *,
        company_id: uuid.UUID,
        name: str,
        phone: str = "",
        email: str = "",
        source: str = "web",
        external_id: str = "",
    ) -> Customer:
        customer = Customer(
            company_id=company_id,
            name=name,
            phone=phone,
            email=email,
            source=source,
            external_id=external_id,
        )
        self.db.add(customer)
        return customer

    def list_customers(self) -> list[Customer]:
        stmt = select(Customer).order_by(Customer.created_at.desc())
        return list(self.db.scalars(stmt).unique().all())

    def get_customer(self, customer_id: uuid.UUID) -> Customer | None:
        return self.db.get(Customer, customer_id)

    # --- Conversations -----------------------------------------------------

    def create_conversation(
        self,
        *,
        company_id: uuid.UUID,
        customer_id: uuid.UUID,
        channel: str = "web",
        status: str = "open",
        assigned_user_id: uuid.UUID | None = None,
    ) -> Conversation:
        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel=channel,
            status=status,
            assigned_user_id=assigned_user_id,
        )
        self.db.add(conversation)
        return conversation

    def list_conversations(self, company_id: uuid.UUID | None = None) -> list[Conversation]:
        stmt = select(Conversation).order_by(Conversation.updated_at.desc())
        if company_id:
            stmt = stmt.where(Conversation.company_id == company_id)
        return list(self.db.scalars(stmt).unique().all())

    def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        return self.db.get(Conversation, conversation_id)

    # --- Messages ----------------------------------------------------------

    def add_message(
        self,
        conversation: Conversation,
        *,
        content: str,
        sender_type: str = "customer",
        sender_id: uuid.UUID | None = None,
        structured_data: dict[str, Any] | None = None,
    ) -> tuple[ConversationMessage, uuid.UUID | None]:
        message = ConversationMessage(
            conversation_id=conversation.id,
            sender_type=sender_type,
            sender_id=sender_id,
            content=content,
            structured_data=structured_data or {},
        )
        self.db.add(message)
        conversation.status = "open"
        conversation.updated_at = datetime.now(timezone.utc)
        self.db.flush()  # получить message.id

        # Auto-create a processing task for every incoming customer message.
        task_id: uuid.UUID | None = None
        if sender_type == "customer":
            task_service = TaskService(self.db)
            task = task_service.create(
                company_id=conversation.company_id,
                title=f"Обработка сообщения клиента: {content[:80]}",
                objective="process_customer_message",
                input_data={
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                },
            )
            self.db.add(task)
            self.db.flush()
            task_id = task.id

        return message, task_id

    def list_messages(self, conversation_id: uuid.UUID) -> list[ConversationMessage]:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
        )
        return list(self.db.scalars(stmt).unique().all())
