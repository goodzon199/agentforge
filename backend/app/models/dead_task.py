from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class DeadTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A task that exhausted retries and landed in the dead-letter queue.

    Postgres is the source of truth (the Redis ``agentos:tasks:dead`` list is
    only a fast signal for operators); replay reads from here, not from Redis.
    """

    __tablename__ = "dead_tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True, nullable=False, unique=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True, nullable=True
    )

    objective: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exception_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="internal_error")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    dead_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    replayed_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )

    task: Mapped[Task] = relationship("Task", foreign_keys=[task_id])
    replayed: Mapped[Task | None] = relationship("Task", foreign_keys=[replayed_task_id])
