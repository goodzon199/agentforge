from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class SupplierFulfillment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One order line's reality against a supplier (Sprint 4.2).

    When an order is created from a quote, one fulfillment row is created per
    line with the *promised* values taken from the offer. A manager then
    records what actually happened (price charged, delivery days, delivered
    quantity, final status) — the only source of truth for on-time delivery,
    price stability and under-delivery metrics.
    """

    __tablename__ = "supplier_fulfillments"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, nullable=True
    )
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("supplier_offers.id", ondelete="SET NULL"), index=True, nullable=True
    )

    article: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    brand: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    # Promised at offer time (snapshot from the priced offer).
    promised_purchase_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    promised_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_ordered: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Actuals recorded by the manager.
    actual_purchase_price: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    actual_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quantity_delivered: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Supplier order automation (Sprint 4.5). When a purchase is approved and
    # placed, the line carries the supplier's tracking id and its current
    # supplier-side status (accepted / shipped / delivered) for order tracking.
    external_order_id: Mapped[str | None] = mapped_column(
        String(80), index=True, nullable=True
    )
    supplier_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ordered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # delivered / partial / cancelled / returned
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="delivered")
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    supplier: Mapped[Supplier] = relationship("Supplier", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SupplierFulfillment {self.brand} {self.article} "
            f"supplier={self.supplier_id} status={self.status}>"
        )
