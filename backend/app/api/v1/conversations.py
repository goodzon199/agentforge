from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.access import company_scope, ensure_company
from app.api.deps import get_conversation_service, get_current_user
from app.models import Conversation, Task, User
from app.models.enums import ConversationMode
from app.orchestrator.orchestrator import orchestrator
from app.schemas.conversation import (
    ConversationCreate,
    ConversationDetail,
    ConversationRead,
    CustomerCreate,
    CustomerRead,
    MessageCreate,
    MessageRead,
    MessageSent,
)
from app.services.conversation_service import ConversationService

customers_router = APIRouter(prefix="/customers", tags=["customers"])
conversations_router = APIRouter(prefix="/conversations", tags=["conversations"])


def _customer_read(customer) -> CustomerRead:
    return CustomerRead.model_validate(customer)


def _conversation_read(conversation: Conversation) -> ConversationRead:
    return ConversationRead(
        id=conversation.id,
        company_id=conversation.company_id,
        customer_id=conversation.customer_id,
        channel=conversation.channel,
        status=conversation.status,
        mode=conversation.mode.value,
        assigned_user_id=conversation.assigned_user_id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        customer_name=conversation.customer.name,
    )


def _message_read(message, task_id: uuid.UUID | None = None) -> MessageRead:
    return MessageRead(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_type=message.sender_type,
        sender_id=message.sender_id,
        content=message.content,
        structured_data=message.structured_data,
        created_at=message.created_at,
        task_id=task_id,
    )


# --- Customers -------------------------------------------------------------

@customers_router.get("", response_model=list[CustomerRead])
def list_customers(
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    scope = company_scope(user)
    customers = service.list_customers()
    if scope is None:
        return [_customer_read(c) for c in customers]
    return [_customer_read(c) for c in customers if c.company_id == scope]


@customers_router.post("", response_model=CustomerRead, status_code=201)
def create_customer(
    payload: CustomerCreate,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    ensure_company(user, payload.company_id)
    customer = service.create_customer(**payload.model_dump())
    service.db.commit()
    service.db.refresh(customer)
    return _customer_read(customer)


# --- Conversations ---------------------------------------------------------

@conversations_router.get("", response_model=list[ConversationRead])
def list_conversations(
    company_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    scope = company_scope(user)
    if scope is not None:
        company_id = scope
    return [_conversation_read(c) for c in service.list_conversations(company_id)]


@conversations_router.post("", response_model=ConversationRead, status_code=201)
def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    ensure_company(user, payload.company_id)
    if service.get_customer(payload.customer_id) is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    conversation = service.create_conversation(**payload.model_dump())
    service.db.commit()
    service.db.refresh(conversation)
    return _conversation_read(conversation)


@conversations_router.get("/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    conversation = _get_scoped_conversation(conversation_id, service, user)
    return ConversationDetail(
        **_conversation_read(conversation).model_dump(),
        messages=[_message_read(m) for m in conversation.messages],
    )


# --- Mode / human takeover ------------------------------------------------

def _get_scoped_conversation(
    conversation_id: uuid.UUID,
    service: ConversationService,
    user: User,
) -> Conversation:
    conversation = service.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    ensure_company(user, conversation.company_id)
    return conversation


@conversations_router.post("/{conversation_id}/takeover", response_model=ConversationRead)
def takeover_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    """A manager takes over: the AI stops responding, only the manager replies."""
    conversation = _get_scoped_conversation(conversation_id, service, user)
    conversation = service.set_mode(
        conversation, ConversationMode.human_active, user_id=user.id
    )
    service.db.commit()
    service.db.refresh(conversation)
    return _conversation_read(conversation)


@conversations_router.post("/{conversation_id}/release", response_model=ConversationRead)
def release_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    """Give the conversation back to the AI (human -> ai_active)."""
    conversation = _get_scoped_conversation(conversation_id, service, user)
    conversation = service.set_mode(conversation, ConversationMode.ai_active, user_id=user.id)
    service.db.commit()
    service.db.refresh(conversation)
    return _conversation_read(conversation)


@conversations_router.post("/{conversation_id}/pause", response_model=ConversationRead)
def pause_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    conversation = _get_scoped_conversation(conversation_id, service, user)
    conversation = service.set_mode(conversation, ConversationMode.paused, user_id=user.id)
    service.db.commit()
    service.db.refresh(conversation)
    return _conversation_read(conversation)


@conversations_router.post("/{conversation_id}/close", response_model=ConversationRead)
def close_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    conversation = _get_scoped_conversation(conversation_id, service, user)
    conversation = service.set_mode(conversation, ConversationMode.closed, user_id=user.id)
    service.db.commit()
    service.db.refresh(conversation)
    return _conversation_read(conversation)


@conversations_router.post("/{conversation_id}/reopen", response_model=ConversationRead)
def reopen_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    conversation = _get_scoped_conversation(conversation_id, service, user)
    conversation = service.set_mode(conversation, ConversationMode.ai_active, user_id=user.id)
    service.db.commit()
    service.db.refresh(conversation)
    return _conversation_read(conversation)


# --- Messages --------------------------------------------------------------

@conversations_router.get("/{conversation_id}/messages", response_model=list[MessageRead])
def list_messages(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    _get_scoped_conversation(conversation_id, service, user)
    return [_message_read(m) for m in service.list_messages(conversation_id)]


@conversations_router.post(
    "/{conversation_id}/messages", response_model=MessageSent, status_code=201
)
def send_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
):
    conversation = _get_scoped_conversation(conversation_id, service, user)

    message, task_id = service.add_message(
        conversation,
        content=payload.content,
        sender_type=payload.sender_type,
        sender_id=payload.sender_id,
        structured_data=payload.structured_data,
    )
    service.db.commit()
    service.db.refresh(message)

    if task_id is not None:
        # Пропустить задачу через оркестратор (в live — очередь, в тестах — inline).
        task = service.db.get(Task, task_id)
        orchestrator.submit(service.db, task)

    return MessageSent(message=_message_read(message), task_id=task_id)
