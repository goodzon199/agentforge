from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import UUID, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class PackGrantStatus(str, enum.Enum):
    """Lifecycle of a permission grant (sprint 5.9.2).

    ``inactive_not_declared``: the pack removed the permission from its
    manifest — the grant stops contributing to effective permissions but is
    kept for audit/history (and HIGH-risk re-review on return).
    """

    active = "active"
    inactive_not_declared = "inactive_not_declared"
    revoked = "revoked"


class PackGrantSource(str, enum.Enum):
    migration_bootstrap = "migration_bootstrap"  # one-time builtin trust transfer
    admin = "admin"


class PackPermissionGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An admin-issued right of a pack to use a platform permission.

    Key dimension is ``(tenant_id, pack_id, permission)``; ``tenant_id IS
    NULL`` means a global grant. Effective rights are always recomputed as
    ``declared ∩ granted`` — the manifest never grants anything.
    """

    __tablename__ = "pack_permission_grants"

    pack_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    permission: Mapped[str] = mapped_column(String(80), nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PackGrantStatus.active.value
    )
    grant_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PackGrantSource.admin.value
    )

    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    granted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PackDeclaredPermission(UUIDPrimaryKeyMixin, Base):
    """Materialized projection of manifest permissions per pack version.

    Rows are soft-removed (``removed_at``) so upgrades produce a reviewable
    diff and the audit trail survives manifest changes.
    """

    __tablename__ = "pack_declared_permissions"

    pack_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(80), nullable=False)
    manifest_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    declared_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    removed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
