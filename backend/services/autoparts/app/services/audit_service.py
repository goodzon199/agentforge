from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.services.audit_context import get_audit_context


def _truncate_timestamp(expr, dialect_name: str):
    """Second-precision normalization of a timestamp expression/value.

    SQLite stores ``func.now()`` server defaults at second precision while the
    ``DateTime`` bind processor emits microseconds, which silently breaks
    ``==``/``<`` comparisons (''-suffix sorts before '.ffffff'). Truncating both
    sides to seconds keeps cursor/date comparisons deterministic on sqlite and
    postgres alike.
    """
    if dialect_name == "sqlite":
        return func.strftime("%Y-%m-%d %H:%M:%S", expr)
    return func.date_trunc("second", expr)


@dataclass(frozen=True)
class AuditCursor:
    """Opaque page marker: the (created_at, id) of the last row returned."""

    created_at: datetime
    event_id: uuid.UUID

    @classmethod
    def decode(cls, raw: str) -> AuditCursor | None:
        try:
            decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
            created_raw, id_raw = decoded.split("|", 1)
            created = datetime.fromisoformat(created_raw)
            return cls(created_at=created, event_id=uuid.UUID(id_raw))
        except (ValueError, UnicodeDecodeError, TypeError):
            return None

    def encode(self) -> str:
        return base64.urlsafe_b64encode(
            f"{self.created_at.isoformat()}|{self.event_id}".encode()
        ).decode("ascii")


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
        request_id: str | None = None,
        user_agent: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditEvent:
        # Fill request metadata from the middleware-populated context when the
        # caller did not provide it explicitly (the audit layer stays unaware
        # of FastAPI: it only reads the contextvar structure).
        ctx = get_audit_context()
        if ctx is not None:
            if ip_address is None:
                ip_address = ctx.ip_address
            if request_id is None:
                request_id = ctx.request_id
            if user_agent is None:
                user_agent = ctx.user_agent
            if user_id is None:
                user_id = ctx.user_id
            if company_id is None:
                company_id = ctx.company_id
        event = AuditEvent(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            company_id=company_id,
            user_id=user_id,
            actor_type=actor_type,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
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

    def list_cursor(
        self,
        *,
        company_id: uuid.UUID | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        user_id: uuid.UUID | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        cursor: AuditCursor | None = None,
        limit: int = 50,
    ) -> list[AuditEvent]:
        """Cursor-paginated listing ordered by (created_at desc, id desc).

        ``cursor`` is the opaque marker returned as ``next_cursor``: it pins
        the exact (created_at, id) of the last row of the previous page so
        new inserts can never shift or duplicate pages.
        """
        stmt = (
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(min(limit, 500))
        )
        dialect = self.db.get_bind().dialect.name
        if company_id is not None:
            stmt = stmt.where(AuditEvent.company_id == company_id)
        if action:
            stmt = stmt.where(AuditEvent.action == action)
        if entity_type:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        if user_id is not None:
            stmt = stmt.where(AuditEvent.user_id == user_id)
        if date_from is not None:
            stmt = stmt.where(
                _truncate_timestamp(AuditEvent.created_at, dialect)
                >= _truncate_timestamp(date_from, dialect)
            )
        if date_to is not None:
            stmt = stmt.where(
                _truncate_timestamp(AuditEvent.created_at, dialect)
                <= _truncate_timestamp(date_to, dialect)
            )
        if cursor is not None:
            cursor_ts = _truncate_timestamp(cursor.created_at, dialect)
            stmt = stmt.where(
                sa.or_(
                    sa.and_(
                        _truncate_timestamp(AuditEvent.created_at, dialect) == cursor_ts,
                        AuditEvent.id < cursor.event_id,
                    ),
                    _truncate_timestamp(AuditEvent.created_at, dialect) < cursor_ts,
                )
            )
        return list(self.db.scalars(stmt).unique().all())

    def count(self, *, company_id: uuid.UUID | None = None) -> int:
        stmt = select(func.count()).select_from(AuditEvent)
        if company_id is not None:
            stmt = stmt.where(AuditEvent.company_id == company_id)
        return self.db.scalar(stmt) or 0
