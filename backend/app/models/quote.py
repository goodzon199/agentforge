from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import QuoteStatus


class Quote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A customer quote formed by the pricing engine (sprint 2.4) and driven
    through the sales funnel (sprint 2.5: draft -> pending_approval -> sent).

    ``items`` is a snapshot of the priced offers the quote is built from — the
    single source of truth for SalesAgent and QuoteGuard (an AI may never
    change a price, only the system computes them).
    """

    __tablename__ = "quotes"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    part_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("part_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    best_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("supplier_offers.id", ondelete="SET NULL"), index=True, nullable=True
    )

    status: Mapped[QuoteStatus] = mapped_column(
        Enum(QuoteStatus, name="quote_status"),
        nullable=False,
        default=QuoteStatus.draft,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    quote_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # Draft prepared by SalesAgent / edited by the manager. final_message is
    # the text actually delivered to the customer.
    ai_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_edited: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # QuoteGuard result for the latest draft.
    guard_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    guard_errors: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Which SalesAgent prompt version produced ai_draft (sprint 3.2).
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Quote {self.part_request_id} status={self.status.value}>"
