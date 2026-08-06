from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AgentStatus, AgentType


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    A digital employee.

    Each agent is a live object with identity, goal, instructions,
    memory, tools, permissions, model configuration and statistics.
    """

    __tablename__ = "agents"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Identity
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)

    # Behaviour contract
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    type: Mapped[AgentType] = mapped_column(
        Enum(AgentType, name="agent_type"), nullable=False, default=AgentType.general
    )

    # Capabilities
    tools: Mapped[list[AgentTool]] = relationship(
        "AgentTool",
        back_populates="agent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    permissions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Model configuration
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="gpt-4o-mini")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)

    # Runtime
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, name="agent_status"), nullable=False, default=AgentStatus.idle
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Statistics
    tasks_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tasks_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tasks_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_llm_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    company: Mapped["Company"] = relationship("Company", back_populates="agents")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Agent {self.name!r} ({self.slug}) role={self.role!r}>"


class AgentTool(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Link between an agent and a tool instance with per-agent config."""

    __tablename__ = "agent_tools"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    agent: Mapped[Agent] = relationship("Agent", back_populates="tools")

    __table_args__ = (UniqueConstraint("agent_id", "tool_name"),)
