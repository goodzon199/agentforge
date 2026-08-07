from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ConversationMode


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A dialogue thread between a customer and the platform."""

    __tablename__ = "conversations"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    channel: Mapped[str] = mapped_column(String(40), nullable=False, default="web")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open")
    mode: Mapped[ConversationMode] = mapped_column(
        Enum(ConversationMode, name="conversation_mode"),
        nullable=False,
        default=ConversationMode.ai_active,
        server_default=ConversationMode.ai_active.value,
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )

    customer: Mapped["Customer"] = relationship("Customer", back_populates="conversations")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        "ConversationMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.created_at.asc()",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Conversation {self.customer_id} channel={self.channel} status={self.status}>"
