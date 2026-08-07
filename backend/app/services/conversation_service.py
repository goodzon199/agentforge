from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.risk import risk_for
from app.models import AgentAction, Conversation, ConversationMessage, Customer
from app.models.enums import AgentActionStatus, ConversationMode
from app.services.task_service import TaskService


class ConversationService:
    """Owns customers, conversations and their messages."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Conversation mode (sprint 3 human takeover) -----------------------

    @staticmethod
    def can_agent_act(conversation: Conversation) -> bool:
        """Whether the AI may autonomously drive this conversation.

        When a human has taken over (human_active) or the conversation is
        paused/closed, the agent must stay silent and only the manager replies.
        """
        return conversation.mode == ConversationMode.ai_active

    def set_mode(
        self,
        conversation: Conversation,
        mode: ConversationMode,
        *,
        user_id: uuid.UUID | None = None,
    ) -> Conversation:
        """Switch who drives the conversation and record the audit trail."""
        if mode == conversation.mode:
            return conversation

        action_type = {
            ConversationMode.human_active: "conversation_takeover",
            ConversationMode.ai_active: (
                "conversation_reopen"
                if conversation.mode == ConversationMode.closed
                else "conversation_release"
            ),
            ConversationMode.paused: "conversation_pause",
            ConversationMode.closed: "conversation_close",
        }[mode]

        conversation.mode = mode
        if mode == ConversationMode.human_active:
            conversation.assigned_user_id = user_id
        conversation.updated_at = datetime.now(timezone.utc)

        self.db.add(
            AgentAction(
                company_id=conversation.company_id,
                action_type=action_type,
                target_type="conversation",
                target_id=str(conversation.id),
                input_data={"conversation_id": str(conversation.id)},
                result_data={"mode": mode.value},
                risk_level=risk_for(action_type),
                status=AgentActionStatus.executed,
                executed_at=datetime.now(timezone.utc),
            )
        )
        return conversation

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
        mode: str = "ai_active",
        assigned_user_id: uuid.UUID | None = None,
    ) -> Conversation:
        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel=channel,
            status=status,
            mode=ConversationMode(mode),
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

        # Auto-create a processing task for every incoming customer message —
        # unless a human has taken over (or the conversation is paused/closed).
        # In those modes the agent stays silent and the manager replies instead.
        task_id: uuid.UUID | None = None
        if sender_type == "customer" and self.can_agent_act(conversation):
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

            # If a sent quote awaits acceptance, a positive customer reply
            # flips the quote to `accepted` (order conversion is then up to a
            # human). Lazy import: order_service depends on this module.
            from app.services.order_service import OrderService

            OrderService(self.db).accept_if_customer_confirms(conversation, content)

        return message, task_id

    def list_messages(self, conversation_id: uuid.UUID) -> list[ConversationMessage]:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at.asc())
        )
        return list(self.db.scalars(stmt).unique().all())
