from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A parts supplier of a company, backed by an adapter (mock / CSV).

    ``settings`` carries the adapter configuration (e.g. for CSV adapters:
    ``{file_path, delimiter, encoding, columns}``).
    """

    __tablename__ = "suppliers"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), index=True, nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(40), nullable=False, default="mock")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Supplier {self.name!r} adapter={self.adapter_type} active={self.is_active}>"
