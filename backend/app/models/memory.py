from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import MemoryType


class ShortMemory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Working / episodic memory: recent context for an agent (agent-context window).
    Entries have a TTL and are used to build the next prompt context.
    """

    __tablename__ = "short_memories"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False, default="interaction")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent: Mapped["Agent"] = relationship("Agent")


class LongMemory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Long-term memory: consolidated facts and lessons learned.
    Stored as compact (embedding-ready) notes attached to an agent.
    """

    __tablename__ = "long_memories"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(60), nullable=False, default="lesson")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    agent: Mapped["Agent"] = relationship("Agent")


class KnowledgeEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Knowledge Base: structured company knowledge available to all agents.
    """

    __tablename__ = "knowledge_entries"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class MemoryEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Unified memory log view (optional indexing of all memory writes).
    """

    __tablename__ = "memory_entries"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    memory_type: Mapped[MemoryType] = mapped_column(
        Enum(MemoryType, name="memory_type"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    agent: Mapped["Agent"] = relationship("Agent")
