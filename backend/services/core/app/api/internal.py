from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from shared.internal import require_internal_token
from shared.pack_security import bearer_from_headers
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.workload import (
    PackWorkloadPrincipal,
    WorkloadDenyReason,
)
from app.models import Agent, Company, Conversation, ConversationMessage, Customer
from app.services.workload_token_service import (
    WorkloadTokenService,
    WorkloadVerificationError,
)

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


# --- Workload principal (sprint 5.9.3) ----------------------------------------
#
# Context API accepts ONLY workload tokens (invariant I1): a service JWT or
# a dispatch token is a token-confusion attempt and gets 401.

_STATUS_BY_REASON = {
    # authentication problems → 401
    "token_invalid": 401,
    "identity_missing": 401,
    "identity_disabled": 401,
    "credential_version_mismatch": 401,
    "token_revoked": 401,
    # authenticated but not authorized → 403
    "permission_missing": 403,
    "grant_revoked": 403,
}


def require_workload_permission(permission: str):
    """Dependency factory: verified workload principal with ``permission``.

    Implements pipeline 5A.5 up to the permission check; tenant/object
    checks stay with the handler (they know the resource).
    """

    def dependency(
        request: Request,
        db: Session = Depends(get_db),
    ) -> PackWorkloadPrincipal:
        svc = WorkloadTokenService(db)
        token = bearer_from_headers(request.headers)
        try:
            if not token:
                raise WorkloadVerificationError(
                    WorkloadDenyReason.token_invalid,
                    "Требуется Bearer workload token.",
                )
            principal = svc.verify(token)
            svc.recheck_grant(principal, permission)
            return principal
        except WorkloadVerificationError as exc:
            status = _STATUS_BY_REASON.get(exc.reason.value, 401)
            svc.deny(None, exc.reason, permission=permission, extra=exc.detail)
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    return dependency


_require_conversation_read = require_workload_permission("conversation.read")
_require_customer_read = require_workload_permission("customer.read")


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
    principal: PackWorkloadPrincipal = Depends(_require_conversation_read),
    limit: int = 20,
) -> dict[str, Any]:
    """Pull-based conversation context for packs.

    Sprint 5.9.3: workload-only. The token's tenant must match the
    conversation's company (else 404 — no existence oracle) and the object
    must be inside the explicit scope (else 403). The embedded customer
    summary is included only when the principal also holds ``customer.read``
    with that customer in scope.
    """
    svc = WorkloadTokenService(db)
    conversation = _get_or_404(db, Conversation, conversation_id)
    svc.authorize_object(
        principal,
        "conversation",
        str(conversation.id),
        resource_tenant_id=str(conversation.company_id),
    )
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
    customer_block: dict[str, Any] | None = None
    if (
        customer is not None
        and "customer.read" in principal.permissions
        and principal.scope.allows("customer", str(customer.id))
    ):
        customer_block = {
            "id": str(customer.id),
            "name": customer.name,
            "email": customer.email or "",
            "phone": customer.phone or "",
        }
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
        "customer": customer_block,
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
    principal: PackWorkloadPrincipal = Depends(_require_customer_read),
) -> dict[str, Any]:
    """Pull-based customer profile for packs (workload-only since 5.9.3)."""
    svc = WorkloadTokenService(db)
    customer = _get_or_404(db, Customer, customer_id)
    svc.authorize_object(
        principal,
        "customer",
        str(customer.id),
        resource_tenant_id=str(customer.company_id),
    )
    conversation_ids = db.scalars(
        select(Conversation.id)
        .where(Conversation.customer_id == customer.id)
        .where(Conversation.company_id == customer.company_id)
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
