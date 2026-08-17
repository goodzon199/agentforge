from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Platform user. company_id scopes a user to a tenant (approvals/actions)."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(180), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Bootstrap/temporary accounts must set a real password at first login.
    # While True, get_current_user only allows /auth/change-password and /auth/me.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Access level inside the tenant: owner | admin | manager | viewer
    # (default "manager"). The seeded bootstrap admin is the "owner".
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="manager")
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True, nullable=True
    )
