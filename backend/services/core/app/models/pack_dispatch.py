from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, Enum, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class PackDispatchStatus(str, enum.Enum):
    """Lifecycle of one core→pack workload dispatch (sprint 5.9.3).

    A workload token is bound to its dispatch row; tokens whose dispatch is
    not ``active`` are rejected (replay / post-completion use).
    """

    active = "active"
    completed = "completed"
    failed = "failed"
    superseded = "superseded"


class PackDispatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persistence for the active-dispatch binding (contract 5A.8).

    One row per core→pack dispatch carrying a workload token. Replay issues
    a new dispatch and supersedes the previous active row of the same task,
    which instantly invalidates the old token regardless of exp.
    """

    __tablename__ = "pack_dispatches"
    __table_args__ = (
        Index("ix_pack_dispatches_task_status", "task_id", "status"),
        Index("ix_pack_dispatches_pack_status", "pack_id", "status"),
    )

    dispatch_id: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    pack_id: Mapped[str] = mapped_column(String(80), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    operation: Mapped[str] = mapped_column(String(160), nullable=False)
    workload_jti: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[PackDispatchStatus] = mapped_column(
        Enum(PackDispatchStatus, name="pack_dispatch_status"),
        nullable=False,
        default=PackDispatchStatus.active,
    )

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    replayed_from: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PackDispatch {self.dispatch_id} pack={self.pack_id} status={self.status.value}>"
