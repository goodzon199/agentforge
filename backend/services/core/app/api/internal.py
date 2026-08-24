from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from shared.internal import require_internal_token
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Agent, Company, Conversation, ConversationMessage, Customer, Pack

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)

# Sprint 5.9.1: token issuance must be reachable WITHOUT the legacy shared
# token — the bootstrap secret is the credential. Guarded by pack identity.
token_router = APIRouter(prefix="/internal", tags=["internal"])


@token_router.post("/token")
def issue_pack_token(
    db: Session = Depends(get_db),
    x_pack_id: str | None = Header(default=None, alias="X-Pack-Id"),
    x_pack_credential: str | None = Header(default=None, alias="X-Pack-Credential"),
) -> dict[str, Any]:
    """Exchange a pack bootstrap secret for a short-lived service JWT.

    The service token proves identity only: it carries neither tenant_id nor
    permissions. Tenant-scoped access is granted exclusively through
    workload tokens minted by core during dispatch (5.9.3).
    """
    from app.services.pack_identity_service import PackIdentityService

    identity = PackIdentityService(db).authenticate(x_pack_id or "", x_pack_credential)
    token, ttl = PackIdentityService(db).issue_service_token(identity)
    db.commit()
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "pack_id": identity.pack_id,
        "credential_version": identity.credential_version,
    }


def _get_or_404(db: Session, model, entity_id: str):
    try:
        record = db.get(model, uuid.UUID(entity_id))
    except (ValueError, TypeError):
        record = None
    if record is None:
        raise HTTPException(status_code=404, detail="Сущность не найдена.")
    return record


def _require_pack_permission(
    db: Session,
    pack_name: str | None,
    permission: str,
) -> Pack:
    """Pack Security gate for pull-based context reads (sprint 5.8.3).

    A pack may fetch core-owned context only when its manifest declares the
    matching permission (``conversation.read`` / ``customer.read``). The
    shared internal token authenticates the call; ``X-Pack-Name`` identifies
    the caller until per-pack credentials land in sprint 5.9.
    """
    if not pack_name:
        raise HTTPException(
            status_code=403,
            detail="Заголовок X-Pack-Name обязателен для Context API.",
        )
    pack = db.scalars(select(Pack).where(Pack.name == pack_name)).first()
    if pack is None or not pack.is_active:
        raise HTTPException(
            status_code=403,
            detail=f"Пак {pack_name!r} не зарегистрирован или не активен.",
        )
    if permission not in (pack.permissions or []):
        raise HTTPException(
            status_code=403,
            detail=f"У пака {pack_name!r} нет разрешения {permission}.",
        )
    return pack


@router.get("/company/{company_id}")
def company_context(company_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Company context for domain work (policy/identity, contract §3)."""
    company = _get_or_404(db, Company, company_id)
    return {
        "id": str(company.id),
        "name": company.name,
        "slug": company.slug,
        "is_active": company.is_active,
        "agent_quota": company.agent_quota,
    }


@router.get("/agent/{agent_id}")
def agent_identity(agent_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Agent identity for domain-side execution (contract §3)."""
    agent = _get_or_404(db, Agent, agent_id)
    return {
        "id": str(agent.id),
        "slug": agent.slug,
        "name": agent.name,
        "type": agent.type.value if hasattr(agent.type, "value") else agent.type,
        "model": agent.model,
        "is_active": agent.is_active,
    }


@router.get("/context/conversations/{conversation_id}")
def context_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    x_pack_name: str | None = Header(default=None),
    limit: int = 20,
) -> dict[str, Any]:
    """Pull-based conversation context for packs (sprint 5.8.3).

    Requires the calling pack to declare ``conversation.read``. Returns the
    conversation, its recent messages and a customer summary — the same shape
    core ships proactively in the dispatch payload's ``history``.
    """
    _require_pack_permission(db, x_pack_name, "conversation.read")
    conversation = _get_or_404(db, Conversation, conversation_id)
    limit = max(1, min(limit, 100))
    messages = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation.id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(limit)
    ).all()
    customer = (
        db.get(Customer, conversation.customer_id)
        if conversation.customer_id
        else None
    )
    return {
        "conversation": {
            "id": str(conversation.id),
            "channel": conversation.channel,
            "status": conversation.status,
            "mode": (
                conversation.mode.value
                if hasattr(conversation.mode, "value")
                else conversation.mode
            ),
        },
        "customer": (
            {
                "id": str(customer.id),
                "name": customer.name,
                "email": customer.email or "",
                "phone": customer.phone or "",
            }
            if customer is not None
            else None
        ),
        "messages": [
            {
                "id": str(m.id),
                "sender_type": m.sender_type,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in reversed(messages)
        ],
    }


@router.get("/context/customers/{customer_id}")
def context_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    x_pack_name: str | None = Header(default=None),
) -> dict[str, Any]:
    """Pull-based customer profile for packs (sprint 5.8.3).

    Requires the calling pack to declare ``customer.read``.
    """
    _require_pack_permission(db, x_pack_name, "customer.read")
    customer = _get_or_404(db, Customer, customer_id)
    conversation_ids = db.scalars(
        select(Conversation.id).where(Conversation.customer_id == customer.id)
    ).all()
    return {
        "id": str(customer.id),
        "name": customer.name,
        "email": customer.email or "",
        "phone": customer.phone or "",
        "source": customer.source,
        "external_id": customer.external_id or "",
        "conversation_ids": [str(cid) for cid in conversation_ids],
    }


@router.get("/health")
def internal_health() -> dict[str, str]:
    return {"status": "ok", "service": "core"}
