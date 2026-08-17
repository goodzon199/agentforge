from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class CatalogFitment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A catalog compatibility record (Sprint 4.0 — Fitment Engine).

    States which article/brand is known to fit which vehicle(s). This is the
    "catalog fitment + OEM + cross references" knowledge base: it is seeded
    from public catalogs and can be enriched from supplier cross-references
    (e.g. Rossko ``is_cross`` offers) and manager confirmations.
    """

    __tablename__ = "catalog_fitments"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    article: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    brand: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    part_name: Mapped[str] = mapped_column(String(240), nullable=False, default="")

    # Vehicle scope this article fits. Null = fits all vehicles of the brand.
    vehicle_brand: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    vehicle_model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    year_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    # Where the record came from: oem / catalog / cross / manager_confirmation.
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="catalog")
    # The original-equipment number this article maps to (OEM / cross).
    oem_article: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # How strongly this record asserts compatibility (0..1).
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.9)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CatalogFitment {self.brand} {self.article} -> "
            f"{self.vehicle_brand} {self.vehicle_model}>"
        )


class CrossReference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An article cross-reference (analog / replacement number).

    E.g. TRW GDB3410 == BREMBO P85112 == BMW 34112283435. Lets the engine
    bridge an unknown article to a known-fit OEM number.
    """

    __tablename__ = "cross_references"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_article: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    source_brand: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    target_article: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_brand: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # How reliable this equivalence is (0..1). 1.0 = identical OEM number.
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.8)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="catalog")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CrossReference {self.source_brand} {self.source_article} "
            f"== {self.target_brand} {self.target_article}>"
        )


class PartReturn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A returned / exchanged / refused part (Sprint 4.0 — Fitment Engine).

    The strongest negative signal for fitment: if the same article was
    returned for the same vehicle, the engine must treat it as doubtful
    instead of trusting the catalog blindly.
    """

    __tablename__ = "part_returns"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Sprint 4.2: which supplier is blamed for the bad part. Null for legacy
    # returns recorded before supplier attribution existed.
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), index=True, nullable=True
    )
    part_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("part_requests.id", ondelete="SET NULL"), index=True, nullable=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, nullable=True
    )
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quotes.id", ondelete="SET NULL"), index=True, nullable=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), index=True, nullable=True
    )

    article: Mapped[str] = mapped_column(String(120), nullable=False)
    brand: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # returned / exchanged / wrong_fitment / refused
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="returned")

    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PartReturn {self.brand} {self.article} status={self.status}>"


class PartFitmentEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Accumulated fitment evidence for one (part_request, article, vehicle).

    The learning moat of the engine: every manager confirmation, every order,
    every return, every supplier cross-reference adds a row here, so the
    confidence grows with real usage — not just with catalog data.
    """

    __tablename__ = "part_fitment_evidence"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    part_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("part_requests.id", ondelete="CASCADE"), index=True, nullable=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), index=True, nullable=True
    )
    article: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    brand: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    # Who created this evidence (sprint 4.1): a user (manager) or None.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # Manager verdict when the evidence is a manual verification:
    # confirmed / rejected (sprint 4.1). Null = not a manual verdict.
    result: Mapped[str | None] = mapped_column(String(24), nullable=True)

    # Source of this evidence: order_history / manager_confirmation / shadow /
    # manager / catalog / cross / supplier / return.
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    # Direction and strength: +0..1 supports fitment, negative = doubts it.
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.0)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PartFitmentEvidence {self.article} {self.source}={self.confidence}>"
