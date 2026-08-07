from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AgentFeedbackType


class AgentFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How a human corrected an agent's output.

    ``original_output`` vs ``final_output`` — the pair of AI draft and what was
    actually delivered — is the learning moat of the platform: it tells us
    exactly what managers keep fixing in AI-generated content.
    """

    __tablename__ = "agent_feedback"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_actions.id", ondelete="SET NULL"), index=True, nullable=True
    )

    feedback_type: Mapped[AgentFeedbackType] = mapped_column(
        Enum(AgentFeedbackType, name="agent_feedback_type"), nullable=False
    )
    original_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Which prompt version produced the output being reviewed (sprint 3.2).
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentFeedback {self.feedback_type.value}>"
