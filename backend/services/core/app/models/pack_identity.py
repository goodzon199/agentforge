from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPrimaryKeyMixin


class PackIdentityStatus(str, enum.Enum):
    """Lifecycle of a pack's cryptographic identity (sprint 5.9.1)."""

    active = "active"
    disabled = "disabled"
    revoked = "revoked"


class PackIdentity(UUIDPrimaryKeyMixin, Base):
    """Per-pack cryptographic identity (sprint 5.9.1).

    Replaces the shared internal token: every installed pack owns a
    bootstrap secret (proves "I am AutoParts" to core) and a per-pack
    dispatch secret (core signs ``aud=pack:<name>`` dispatch tokens with
    it; the pack verifies them). Plaintext secrets are shown once at
    provision/rotate time — only hashes live in the database.
    """

    __tablename__ = "pack_identities"

    pack_id: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    service_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    status: Mapped[PackIdentityStatus] = mapped_column(
        Enum(PackIdentityStatus, name="pack_identity_status"),
        nullable=False,
        default=PackIdentityStatus.active,
    )

    # PBKDF2 hash of the pack's token-endpoint credential.
    bootstrap_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Fast sha256 fingerprint of the mounted dispatch secret material,
    # used to verify the right version is deployed (not for auth).
    dispatch_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    rotated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_authenticated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PackIdentity {self.pack_id} status={self.status.value} "
            f"cv={self.credential_version}>"
        )
