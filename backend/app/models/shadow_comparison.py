from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin

# Shadow Comparison lifecycle. "pending" while Agentos works and the manager
# has not submitted their own selection; "completed" once the manager submits
# and the comparison is evaluated.
SHADOW_STATUS_PENDING = "pending"
SHADOW_STATUS_COMPLETED = "completed"


class ShadowComparison(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Shadow Mode (sprint 3.8.1): one request run in parallel by AI and manager.

    The AI side (vehicle / part / article / offers / price) is snapshotted when
    the request is ingested; the manager side is captured when the manager
    submits their own selection. The two are compared without the AI answer
    ever reaching the customer.
    """

    __tablename__ = "shadow_comparisons"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    part_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("part_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SHADOW_STATUS_PENDING
    )

    # --- AI snapshot (taken at intake / from the finished selection) --------
    ai_vehicle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ai_part: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    ai_article: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    ai_offer_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ai_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    ai_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # --- Manager snapshot (submitted by the manager) ------------------------
    manager_vehicle: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manager_part: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    manager_article: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    manager_offer_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    manager_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    manager_reply: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # --- Comparison results -------------------------------------------------
    vehicle_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    part_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    oem_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    offer_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_delta: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    part_request: Mapped[Any] = relationship("PartRequest")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ShadowComparison {self.part_request_id} status={self.status}>"
