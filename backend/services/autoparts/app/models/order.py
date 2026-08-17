from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import OrderStatus, TrackingStatus


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An order converted from an accepted quote (sprint 2.6).

    Only a human may create an order (create_order is a HIGH-risk action), so
    OrderService.create_from_quote requires a superuser. ``items`` is the same
    customer-facing snapshot the quote was built from — order line items are
    never renegotiated by an agent.
    """

    __tablename__ = "orders"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    part_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("part_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quotes.id", ondelete="SET NULL"), index=True, nullable=True
    )

    order_number: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"),
        nullable=False,
        default=OrderStatus.new,
    )
    # Supplier-side aggregate lifecycle (sprint 4.6): accepted → assembling →
    # shipped → arrived → handed_over. Recomputed from the fulfillment lines'
    # supplier_status; "pending" until the purchase is approved and placed.
    tracking_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=TrackingStatus.pending.value
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    order_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order {self.order_number} status={self.status.value}>"
