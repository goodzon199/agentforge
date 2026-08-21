from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import check_public_business_rate, get_conversation_service
from app.core.config import settings
from app.core.emergency import emergency_switch
from app.core.rate_limit import RateLimiter
from app.schemas.chat import (
    PublicChatMessageIn,
    PublicChatMessageRead,
    PublicChatMessages,
    PublicChatSent,
    PublicChatStart,
    PublicChatStarted,
)
from app.services.chat_service import ChatError, WebchatService
from app.services.conversation_service import ConversationService

router = APIRouter(prefix="/public/chat", tags=["public-chat"])

_limiter = RateLimiter()


def _service(db) -> WebchatService:
    return WebchatService(db)


def _message_read(message) -> PublicChatMessageRead:
    return PublicChatMessageRead(
        id=message.id,
        sender_type=message.sender_type,
        content=message.content,
        created_at=message.created_at,
    )


def _require_active() -> None:
    if emergency_switch.is_engaged():
        raise HTTPException(
            status_code=503,
            detail="Пилотная эксплуатация временно приостановлена. Попробуйте позже.",
        )


@router.post("/start", response_model=PublicChatStarted)
def start_chat(
    payload: PublicChatStart,
    request: Request,
    conversation_service: ConversationService = Depends(get_conversation_service),
    _: None = Depends(check_public_business_rate),
):
    _require_active()
    client_ip = request.client.host if request.client else "unknown"
    bucket = f"{payload.client_key or 'anon'}:{client_ip}"
    if not _limiter.hit(
        f"rate:chat:start:{bucket}",
        settings.chat_rate_per_minute,
        settings.chat_rate_window_seconds,
    ):
        raise HTTPException(
            status_code=429,
            detail="Слишком много новых чатов. Попробуйте позже.",
        )
    service = _service(conversation_service.db)
    try:
        conversation, customer = service.start(
            public_token=payload.public_token,
            visitor_name=payload.visitor_name,
            client_key=payload.client_key,
        )
    except ChatError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    conversation_service.db.commit()
    return PublicChatStarted(
        conversation_id=conversation.id,
        customer_id=customer.id,
        company_id=conversation.company_id,
        visitor_name=customer.name,
        client_key=customer.external_id,
        channel=conversation.channel,
        mode=conversation.mode.value,
        status=conversation.status,
    )


@router.post("/messages", response_model=PublicChatSent, status_code=201)
def send_public_message(
    payload: PublicChatMessageIn,
    request: Request,
    conversation_service: ConversationService = Depends(get_conversation_service),
    _: None = Depends(check_public_business_rate),
):
    _require_active()
    client_ip = request.client.host if request.client else "unknown"
    bucket = f"{getattr(payload, 'client_key', None) or 'anon'}:{client_ip}"
    if not _limiter.hit(
        f"rate:chat:min:{bucket}",
        settings.chat_rate_per_minute,
        settings.chat_rate_window_seconds,
    ):
        raise HTTPException(
            status_code=429,
            detail="Слишком много сообщений. Попробуйте через минуту.",
        )
    if not _limiter.hit(
        f"rate:chat:day:{bucket}",
        settings.chat_rate_per_day,
        86_400,
    ):
        raise HTTPException(
            status_code=429,
            detail="Достигнут дневной лимит сообщений.",
        )
    service = _service(conversation_service.db)
    conversation = conversation_service.get_conversation(payload.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    try:
        message, task_id = service.send_message(conversation, payload.content)
    except ChatError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return PublicChatSent(message=_message_read(message), task_id=task_id)


@router.get("/{conversation_id}/messages", response_model=PublicChatMessages)
def list_public_messages(
    conversation_id: uuid.UUID,
    conversation_service: ConversationService = Depends(get_conversation_service),
):
    service = _service(conversation_service.db)
    conversation = conversation_service.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    try:
        messages = service.list_messages(conversation)
    except ChatError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return PublicChatMessages(
        conversation_id=conversation.id,
        mode=conversation.mode.value,
        status=conversation.status,
        messages=[_message_read(m) for m in messages],
    )
