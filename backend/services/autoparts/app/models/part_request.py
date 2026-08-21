from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import PartRequestStatus


class PartRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A structured, stateful request for an auto part.

    The source of truth for an intake: created from a customer message,
    enriched through conversation, and consumed by the parts search.
    """

    __tablename__ = "part_requests"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # Sprint 5.8.3 Pack Context Contract: provenance references to the
    # core-owned conversation/message/customer. Plain UUIDs, no FK — the
    # pack stores references, never copies of core entities.
    core_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    core_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )
    core_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), index=True, nullable=True
    )

    intent: Mapped[str] = mapped_column(String(40), nullable=False, default="part_search")
    part_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    article: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[PartRequestStatus] = mapped_column(
        Enum(PartRequestStatus, name="part_request_status"),
        nullable=False,
        default=PartRequestStatus.collecting_data,
    )
    missing_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    structured_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    vehicle: Mapped[Vehicle | None] = relationship("Vehicle")
    customer: Mapped[Customer] = relationship("Customer")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PartRequest {self.part_name!r} status={self.status}>"
