from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class AuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An immutable record of a security-relevant action (sprint 3.7).

    The journal answers "who did what, when, in whose tenant" for the
    pilot: approval decisions, order creation, task replay, user creation.
    Rows are append-only; never edited or deleted through the API.
    """

    __tablename__ = "audit_events"

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # "user" | "system" | "agent" — who initiated the action.
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    # Dotted action id, e.g. "approval.approve", "order.create", "task.replay".
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Request correlation id (X-Request-ID) and user-agent, captured by the
    # audit-context middleware. request_id links the journal to access logs.
    request_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Free-form JSON with the relevant before/after values (never secrets).
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditEvent {self.action} company={self.company_id} actor={self.user_id}>"


Index("ix_audit_events_company_created", AuditEvent.company_id, AuditEvent.created_at)
Index("ix_audit_events_action_created", AuditEvent.action, AuditEvent.created_at)
