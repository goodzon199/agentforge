from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class CompanyPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Business rules of a company — how its AI employees sell (Sprint 3.5).

    One row per company. Each domain is a JSON document with typed defaults
    (see ``app/core/policies.py``); a company stores only what it explicitly
    overrides, everything else falls back to the defaults. Unlike
    ``PermissionEngine`` (may the agent act?), these policies decide *how* the
    company wants to work: pricing, suppliers, approval thresholds, sales
    wording and security overrides.
    """

    __tablename__ = "company_policies"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    pricing_policy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    supplier_policy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    approval_policy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sales_policy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    security_policy: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CompanyPolicy company_id={self.company_id}>"
