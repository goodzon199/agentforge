from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import AgentActionStatus, ApprovalRiskLevel


class AgentAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An auditable action an agent tried to perform (or performed).

    This is the foundation for the future AgentOS: the platform manages not
    only messages, but also orders, price changes, emails, CRM leads — every
    one of them as a first-class, idempotent, risk-scored action.
    """

    __tablename__ = "agent_actions"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )

    action_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    risk_level: Mapped[ApprovalRiskLevel] = mapped_column(
        Enum(ApprovalRiskLevel, name="agent_action_risk_level"),
        nullable=False,
        default=ApprovalRiskLevel.low,
    )
    status: Mapped[AgentActionStatus] = mapped_column(
        Enum(AgentActionStatus, name="agent_action_status"),
        nullable=False,
        default=AgentActionStatus.pending,
    )
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Double-click protection: an executed action with the same key must not
    # run again (e.g. send_quote:{quote_id}:{conversation_id}).
    idempotency_key: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)

    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentAction {self.action_type} status={self.status.value}>"
