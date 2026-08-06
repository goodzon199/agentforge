from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, KnowledgeEntry, LongMemory, MemoryEntry, ShortMemory
from app.models.enums import MemoryType


class MemoryService:
    """
    Owns the agent memory pipeline:

        Agent -> Short Memory -> Long Memory -> Knowledge Base

    Short memory keeps recent working context; long memory stores
    consolidated lessons; knowledge base holds company-wide facts.
    """

    SHORT_MEMORY_TTL_DAYS = 7

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Writes -----------------------------------------------------------

    def remember_short(
        self,
        agent: Agent,
        content: str,
        kind: str = "interaction",
        meta: dict | None = None,
        ttl_days: int | None = None,
    ) -> ShortMemory:
        entry = ShortMemory(
            agent_id=agent.id,
            kind=kind,
            content=content,
            meta=meta or {},
            expires_at=datetime.utcnow()
            + timedelta(days=ttl_days or self.SHORT_MEMORY_TTL_DAYS),
        )
        self.db.add(entry)
        self._log_entry(agent, MemoryType.short, content, meta)
        return entry

    def remember_long(
        self,
        agent: Agent,
        content: str,
        kind: str = "lesson",
        source_task_id: uuid.UUID | None = None,
        confidence: float = 1.0,
    ) -> LongMemory:
        entry = LongMemory(
            agent_id=agent.id,
            kind=kind,
            content=content,
            source_task_id=source_task_id,
            confidence=confidence,
        )
        self.db.add(entry)
        self._log_entry(agent, MemoryType.long, content, None)
        return entry

    def remember_knowledge(
        self,
        company_id: uuid.UUID,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> KnowledgeEntry:
        entry = KnowledgeEntry(
            company_id=company_id,
            title=title,
            content=content,
            tags=tags or [],
        )
        self.db.add(entry)
        return entry

    # --- Reads ------------------------------------------------------------

    def short_memories(self, agent_id: uuid.UUID, limit: int = 20) -> list[ShortMemory]:
        now = datetime.utcnow()
        stmt = (
            select(ShortMemory)
            .where(ShortMemory.agent_id == agent_id)
            .where((ShortMemory.expires_at.is_(None)) | (ShortMemory.expires_at > now))
            .order_by(ShortMemory.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).unique().all())

    def long_memories(self, agent_id: uuid.UUID, limit: int = 50) -> list[LongMemory]:
        stmt = (
            select(LongMemory)
            .where(LongMemory.agent_id == agent_id)
            .order_by(LongMemory.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt).unique().all())

    def knowledge(self, company_id: uuid.UUID, query: str | None = None, limit: int = 50) -> list[KnowledgeEntry]:
        stmt = select(KnowledgeEntry).where(KnowledgeEntry.company_id == company_id)
        if query:
            stmt = stmt.where(KnowledgeEntry.title.ilike(f"%{query}%"))
        stmt = stmt.order_by(KnowledgeEntry.created_at.desc()).limit(limit)
        return list(self.db.scalars(stmt).unique().all())

    def build_context(self, agent: Agent) -> dict[str, object]:
        """Assemble the memory context used to build an agent's next prompt."""
        return {
            "agent_id": str(agent.id),
            "short": [
                {"kind": m.kind, "content": m.content, "created_at": m.created_at.isoformat()}
                for m in self.short_memories(agent.id)
            ],
            "long": [
                {"kind": m.kind, "content": m.content, "confidence": m.confidence}
                for m in self.long_memories(agent.id)
            ],
        }

    # --- Internals --------------------------------------------------------

    def _log_entry(self, agent: Agent, memory_type: MemoryType, content: str, meta: dict | None) -> None:
        self.db.add(
            MemoryEntry(
                agent_id=agent.id,
                memory_type=memory_type,
                content=content[:1000],
                meta=meta or {},
            )
        )
