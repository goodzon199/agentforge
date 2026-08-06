from __future__ import annotations

import uuid
from decimal import Decimal
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class SupplierOffer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A normalized offer from a supplier for a part request.

    ``purchase_price`` is the supplier's price — visible only to managers and
    the pricing engine, never exposed to the customer-facing layer.
    """

    __tablename__ = "supplier_offers"

    part_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("part_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    search_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("supplier_search_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), index=True, nullable=False
    )

    brand: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    article: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    part_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    purchase_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Stamped by the pricing engine (sprint 2.4). customer_price is the
    # customer-facing unit price, total_price = customer_price * quantity.
    customer_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    total_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    margin_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    supplier: Mapped["Supplier"] = relationship("Supplier", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SupplierOffer {self.brand} {self.article} price={self.purchase_price}>"
