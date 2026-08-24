from __future__ import annotations

import datetime as dt
import hashlib
import secrets as pysecrets
import uuid
from typing import Any

import jwt
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import PackIdentity, PackIdentityStatus


class PackIdentityError(Exception):
    """Raised when identity lifecycle preconditions are violated."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum()) or "pack"


def generate_pack_secret(pack_name: str, kind: str) -> str:
    """Cryptographically random secret (>=256 bit), revealed exactly once."""
    return f"{_slug(pack_name)}_{kind}_sec_{pysecrets.token_urlsafe(32)}"


class PackIdentityService:
    """Lifecycle of per-pack credentials (sprint 5.9.1).

    Plaintext secrets exist only in the return value of ``provision`` /
    ``rotate`` — the database stores PBKDF2 (bootstrap) and sha256
    (dispatch material fingerprint) hashes exclusively.
    """

    def __init__(self, db) -> None:
        self.db = db

    # --- lookup / creation -------------------------------------------------

    def get(self, pack_id: str) -> PackIdentity | None:
        return self.db.scalars(
            select(PackIdentity).where(PackIdentity.pack_id == pack_id)
        ).first()

    def ensure(self, pack_id: str, service_id: str | None = None) -> PackIdentity:
        identity = self.get(pack_id)
        if identity is not None:
            return identity
        identity = PackIdentity(
            pack_id=pack_id,
            service_id=service_id or pack_id,
            status=PackIdentityStatus.active,
            credential_version=1,
            created_at=_now(),
        )
        self.db.add(identity)
        self.db.flush()
        return identity

    # --- provisioning ------------------------------------------------------

    def provision(self, pack_id: str) -> dict[str, Any]:
        """Create or rotate both secrets; plaintext is returned once."""
        identity = self.get(pack_id)
        if identity is None:
            identity = self.ensure(pack_id)
        elif identity.status == PackIdentityStatus.revoked:
            raise PackIdentityError(
                f"Идентичность пака {pack_id!r} отозвана — провижининг невозможен."
            )

        bootstrap_secret = generate_pack_secret(pack_id, "bootstrap")
        dispatch_secret = generate_pack_secret(pack_id, "dispatch")

        rotated = identity.bootstrap_secret_hash != ""  # rotate, not first issue
        identity.bootstrap_secret_hash = hash_password(bootstrap_secret)
        identity.dispatch_secret_hash = hashlib.sha256(
            dispatch_secret.encode("utf-8")
        ).hexdigest()
        if rotated:
            identity.credential_version += 1
            identity.rotated_at = _now()
        self.db.flush()

        return {
            "pack_id": pack_id,
            "service_id": identity.service_id,
            "bootstrap_secret": bootstrap_secret,
            "dispatch_secret": dispatch_secret,
            "credential_version": identity.credential_version,
        }

    # --- lifecycle ---------------------------------------------------------

    def set_status(self, pack_id: str, status: PackIdentityStatus) -> None:
        identity = self.get(pack_id)
        if identity is None:
            return
        identity.status = status
        if status == PackIdentityStatus.revoked:
            identity.revoked_at = _now()
        self.db.flush()

    # --- authentication ----------------------------------------------------

    def authenticate(self, pack_id: str, presented_secret: str | None) -> PackIdentity:
        """Verify a bootstrap secret for POST /internal/token.

        Unknown pack and wrong secret are indistinguishable (401) to avoid
        pack-name enumeration; disabled/revoked identities get explicit 403s.
        """
        identity = self.get(pack_id or "")
        if (
            identity is None
            or not presented_secret
            or not verify_password(presented_secret, identity.bootstrap_secret_hash)
        ):
            raise HTTPException(
                status_code=401,
                detail="PACK_UNAUTHENTICATED: неверный пак или секрет.",
            )
        if identity.status == PackIdentityStatus.disabled:
            raise HTTPException(403, detail="PACK_DISABLED.")
        if identity.status == PackIdentityStatus.revoked:
            raise HTTPException(403, detail="PACK_REVOKED.")

        identity.last_authenticated_at = _now()
        self.db.flush()
        return identity

    # --- tokens ------------------------------------------------------------

    def issue_service_token(self, identity: PackIdentity) -> tuple[str, int]:
        """Service JWT: identity only — no tenant, no permissions."""
        now = _now()
        ttl = settings.internal_jwt_ttl_seconds
        payload = {
            "iss": "agentos-core",
            "sub": f"pack:{identity.pack_id}",
            "aud": "agentos-internal",
            "pack_id": identity.pack_id,
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + dt.timedelta(seconds=ttl),
            "credential_version": identity.credential_version,
        }
        token = jwt.encode(payload, settings.internal_jwt_key, algorithm="HS256")
        return token, ttl

    def issue_dispatch_token(
        self,
        pack_id: str,
        *,
        tenant_id: str | None = None,
        task_id: str | None = None,
        dispatch_id: str | None = None,
    ) -> str | None:
        """Core→Pack token signed with that pack's own dispatch secret.

        Returns None when no secret material is mounted yet (transition
        period — strict enforcement lands in sprint 5.9.4).
        """
        secret = load_dispatch_secret(pack_id)
        if not secret:
            return None
        now = _now()
        payload = {
            "iss": "agentos-core",
            "sub": f"pack:{pack_id}",
            "aud": f"pack:{pack_id}",
            "pack_id": pack_id,
            "jti": uuid.uuid4().hex,
            "iat": now,
            "exp": now + dt.timedelta(seconds=settings.internal_jwt_ttl_seconds),
            "credential_version": self.credential_version_of(pack_id),
        }
        if tenant_id:
            payload["tenant_id"] = tenant_id
        if task_id:
            payload["task_id"] = task_id
        if dispatch_id:
            payload["dispatch_id"] = dispatch_id
        return jwt.encode(payload, secret, algorithm="HS256")

    def credential_version_of(self, pack_id: str) -> int:
        identity = self.get(pack_id)
        return identity.credential_version if identity else 0

    def verify_credential_version(self, payload: dict[str, Any]) -> bool:
        """Token cv must match the live identity version (rotation → 401)."""
        expected = self.credential_version_of(str(payload.get("pack_id", "")))
        presented = payload.get("credential_version")
        return expected > 0 and presented == expected


# --- module-level helpers ---------------------------------------------------


_dispatch_secret_cache: dict[tuple[str, float], str] = {}


def load_dispatch_secret(pack_id: str) -> str | None:
    """Read a per-pack dispatch secret from the mounted secrets directory.

    Docker compose mounts ``.secrets/`` at ``/run/secrets/pack-credentials``;
    the file is ``{pack}-dispatch``. Cached by mtime so dev-side rotation
    via file replacement works without a service restart.
    """
    import os

    path = os.path.join(settings.pack_secrets_dir, f"{_slug(pack_id)}-dispatch")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    cached = _dispatch_secret_cache.get((path, mtime))
    if cached is not None:
        return cached
    with open(path, encoding="utf-8") as fh:
        value = fh.read().strip()
    if value:
        _dispatch_secret_cache[(path, mtime)] = value
    return value or None


def verify_dispatch_token(token: str, *, expected_pack: str, key: str) -> dict[str, Any]:
    """Pack-side verification of a core→pack dispatch token.

    Raises jwt.PyJWTError on any failure; callers translate to 401.
    """
    return jwt.decode(
        token,
        key,
        algorithms=["HS256"],
        issuer="agentos-core",
        audience=f"pack:{expected_pack}",
    )


def verify_internal_service_token(token: str, *, key: str | None = None) -> dict[str, Any] | None:
    """Verify a bearer service/workload JWT issued by core.

    Returns claims or None on any validation failure.
    """
    try:
        return jwt.decode(
            token,
            key if key is not None else settings.internal_jwt_key,
            algorithms=["HS256"],
            issuer="agentos-core",
            audience="agentos-internal",
        )
    except jwt.PyJWTError:
        return None
