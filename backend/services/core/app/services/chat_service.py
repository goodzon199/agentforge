from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Conversation, ConversationMessage, Customer
from app.services.conversation_service import ConversationService


class ChatError(Exception):
    pass


class WebchatService:
    """Public web-chat channel (sprint 3 pilot).

    A site visitor is turned into a Customer (source=webchat) and a
    Conversation, then fed into the exact same pipeline as a regular dialog:
    ConversationService.add_message -> task -> orchestrator -> agent reply.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Entry points -----------------------------------------------------

    def start(
        self,
        *,
        public_token: str,
        visitor_name: str = "Гость",
        client_key: str = "",
    ) -> tuple[Conversation, Customer]:
        company = self.db.scalars(
            select(Company).where(Company.public_token == public_token)
        ).first()
        if company is None:
            raise ChatError("Компания не найдена по публичному токену.")
        if not company.is_active:
            raise ChatError("Компания не активна.")

        customer = self._find_or_create_customer(company, visitor_name, client_key)
        conversation = self._find_or_create_conversation(company, customer)
        return conversation, customer

    def send_message(
        self,
        conversation: Conversation,
        content: str,
    ) -> tuple[ConversationMessage, uuid.UUID | None]:
        if conversation.channel != "webchat":
            raise ChatError("Это не публичный чат.")
        message, task_id = ConversationService(self.db).add_message(
            conversation,
            content=content,
            sender_type="customer",
            sender_id=None,
        )
        self.db.commit()
        if task_id is not None:
            from app.models import Task
            from app.orchestrator.orchestrator import orchestrator

            task = self.db.get(Task, task_id)
            if task is not None:
                orchestrator.submit(self.db, task)
        return message, task_id

    def list_messages(self, conversation: Conversation) -> list[ConversationMessage]:
        if conversation.channel != "webchat":
            raise ChatError("Это не публичный чат.")
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.created_at.asc())
        )
        return list(self.db.scalars(stmt).unique().all())

    # --- Internals --------------------------------------------------------

    def _find_or_create_customer(
        self, company: Company, visitor_name: str, client_key: str
    ) -> Customer:
        conv_service = ConversationService(self.db)
        key = client_key.strip()
        if key:
            stmt = (
                select(Customer)
                .where(Customer.company_id == company.id)
                .where(Customer.source == "webchat")
                .where(Customer.external_id == key)
            )
            customer = self.db.scalars(stmt).first()
            if customer is not None:
                return customer

        customer = conv_service.create_customer(
            company_id=company.id,
            name=visitor_name.strip() or "Гость",
            source="webchat",
            external_id=key or uuid.uuid4().hex,
        )
        self.db.add(customer)
        self.db.flush()
        return customer

    def _find_or_create_conversation(
        self, company: Company, customer: Customer
    ) -> Conversation:
        conv_service = ConversationService(self.db)
        stmt = (
            select(Conversation)
            .where(Conversation.customer_id == customer.id)
            .where(Conversation.company_id == company.id)
            .where(Conversation.channel == "webchat")
            .where(Conversation.status != "closed")
            .order_by(Conversation.created_at.desc())
        )
        existing = self.db.scalars(stmt).first()
        if existing is not None:
            return existing
        conversation = conv_service.create_conversation(
            company_id=company.id,
            customer_id=customer.id,
            channel="webchat",
            status="open",
        )
        self.db.add(conversation)
        self.db.flush()
        return conversation
