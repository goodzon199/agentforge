from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DomainThreadLink(Base):
    """Cross-reference between a core-owned conversation and the pack's
    domain thread (sprint 5.8.3 Pack Context Contract).

    Core is the source of truth for conversations/customers/messages; this
    table is NOT a copy — it maps a core conversation id to the local domain
    aggregates (Conversation/Customer rows) the pack schema requires as FK
    anchors for PartRequest/Quote/Order. Messages and history stay in core.
    """

    __tablename__ = "domain_thread_links"

    core_conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    core_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    core_company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    channel: Mapped[str] = mapped_column(String(40), nullable=False, default="webchat")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DomainThreadLink {self.core_conversation_id} -> conv={self.conversation_id}>"
