from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class PromptVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A versioned system prompt for an agent (sprint 3.2).

    Agents stop reading prompts from code and instead use the active
    ``PromptVersion`` for their kind, which lets us compare quality across
    versions (accept/edit/reject rates) and later run A/B tests.
    """

    __tablename__ = "prompt_versions"

    # null company_id = global default version shared by all companies.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=True
    )
    agent_kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("company_id", "agent_kind", "version", name="uq_prompt_version"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PromptVersion {self.agent_kind}:{self.version} active={self.is_active}>"
