from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from shared.internal import require_internal_token
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Agent, Company

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


def _get_or_404(db: Session, model, entity_id: str):
    try:
        record = db.get(model, uuid.UUID(entity_id))
    except (ValueError, TypeError):
        record = None
    if record is None:
        raise HTTPException(status_code=404, detail="Сущность не найдена.")
    return record


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


@router.get("/health")
def internal_health() -> dict[str, str]:
    return {"status": "ok", "service": "core"}
