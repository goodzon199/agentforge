from __future__ import annotations

import uuid

from sqlalchemy import String, Text, Boolean, Integer
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

    agents: Mapped[list["Agent"]] = relationship("Agent", back_populates="company", lazy="selectin")
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="company", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Company {self.name!r}>"
