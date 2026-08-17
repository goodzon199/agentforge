from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant / organisation that owns agents and tasks."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    agent_quota: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Shadow Mode (sprint 3.8.1): while True, every new part request opens a
    # shadow comparison — Agentos works in parallel with the manager and the
    # results are compared (vehicle/part/OEM/offers/price/time) without the
    # AI answer reaching the customer.
    shadow_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Public token used by the web-chat widget (public channel, no JWT).
    public_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )

    agents: Mapped[list[Agent]] = relationship("Agent", back_populates="company", lazy="selectin")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="company", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Company {self.name!r}>"
