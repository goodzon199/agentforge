from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A company's customer (end-client, not a platform user)."""

    __tablename__ = "customers"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="web")
    external_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    # Sprint 4.4: the customer "garage" and preferences. memory holds the
    # segment preference (economy/middle/premium), the computed average check
    # and free-form preferences; vehicles is the list of their cars.
    memory: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation", back_populates="customer", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Customer {self.name!r}>"
