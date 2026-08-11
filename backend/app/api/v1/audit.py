from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.access import company_scope, ensure_company
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import AuditEvent, User
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventRead(BaseModel):
    id: str
    company_id: str | None = None
    user_id: str | None = None
    actor_type: str
    action: str
    entity_type: str
    entity_id: str | None = None
    ip_address: str | None = None
    detail: dict[str, Any] = {}
    created_at: datetime


class AuditListRead(BaseModel):
    total: int
    items: list[AuditEventRead]


def _read(event: AuditEvent) -> AuditEventRead:
    return AuditEventRead(
        id=str(event.id),
        company_id=str(event.company_id) if event.company_id else None,
        user_id=str(event.user_id) if event.user_id else None,
        actor_type=event.actor_type,
        action=event.action,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        ip_address=event.ip_address,
        detail=event.detail or {},
        created_at=event.created_at,
    )


@router.get("", response_model=AuditListRead)
def list_audit(
    action: str | None = None,
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = AuditService(db)
    scope = company_scope(user)
    events = service.list(
        company_id=scope,
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    return AuditListRead(
        total=service.count(company_id=scope),
        items=[_read(e) for e in events],
    )


@router.get("/{event_id}", response_model=AuditEventRead)
def get_audit_event(
    event_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    event = db.get(AuditEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Запись аудита не найдена")
    ensure_company(user, event.company_id)
    return _read(event)
