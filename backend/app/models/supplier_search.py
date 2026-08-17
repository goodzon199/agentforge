from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SupplierAttemptStatus, SupplierSearchStatus


class SupplierSearchRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One search run over the company's suppliers for a part request.

    A repeated search creates a new run — history is never deleted.
    """

    __tablename__ = "supplier_search_runs"

    part_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("part_requests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[SupplierSearchStatus] = mapped_column(
        Enum(SupplierSearchStatus, name="supplier_search_status"),
        nullable=False,
        default=SupplierSearchStatus.running,
    )
    offers_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppliers_succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suppliers_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    structured_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    attempts: Mapped[list[SupplierSearchAttempt]] = relationship(
        "SupplierSearchAttempt",
        back_populates="run",
        lazy="selectin",
        order_by="SupplierSearchAttempt.created_at.asc()",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SupplierSearchRun {self.part_request_id} status={self.status.value}>"


class SupplierSearchAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Outcome of calling one supplier adapter within a search run."""

    __tablename__ = "supplier_search_attempts"

    search_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("supplier_search_runs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[SupplierAttemptStatus] = mapped_column(
        Enum(SupplierAttemptStatus, name="supplier_attempt_status"),
        nullable=False,
        default=SupplierAttemptStatus.pending,
    )
    offers_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    run: Mapped[SupplierSearchRun] = relationship(
        "SupplierSearchRun", back_populates="attempts"
    )
    supplier: Mapped[Supplier] = relationship("Supplier", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SupplierSearchAttempt supplier={self.supplier_id} status={self.status.value}>"
