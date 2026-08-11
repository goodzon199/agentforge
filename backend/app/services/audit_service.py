from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent


class AuditService:
    """Append-only journal of security-relevant actions (sprint 3.7).

    ``record`` adds a row to the current transaction; callers commit as part
    of the operation they are auditing (no separate commit here so a failed
    business operation never leaves a half-written audit trail).
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str | None = None,
        company_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        actor_type: str = "user",
        ip_address: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            company_id=company_id,
            user_id=user_id,
            actor_type=actor_type,
            ip_address=ip_address,
            detail=detail or {},
        )
        self.db.add(event)
        return event

    def list(
        self,
        *,
        company_id: uuid.UUID | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        user_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        stmt = (
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc())
            .offset(offset)
            .limit(min(limit, 500))
        )
        if company_id is not None:
            stmt = stmt.where(AuditEvent.company_id == company_id)
        if action:
            stmt = stmt.where(AuditEvent.action == action)
        if entity_type:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        if user_id is not None:
            stmt = stmt.where(AuditEvent.user_id == user_id)
        return list(self.db.scalars(stmt).unique().all())

    def count(self, *, company_id: uuid.UUID | None = None) -> int:
        stmt = select(func.count()).select_from(AuditEvent)
        if company_id is not None:
            stmt = stmt.where(AuditEvent.company_id == company_id)
        return self.db.scalar(stmt) or 0
