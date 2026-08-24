"""Pack-side token verification helpers (sprint 5.9).

Packs never hold core's signing key for service/workload tokens — they
receive ready bearer JWTs. For core→pack dispatch calls the signature key
is the pack's own per-pack ``dispatch_secret`` (mounted as a docker secret
file), so a stolen credential of one pack is useless at another pack.
"""

from __future__ import annotations

import os
from typing import Any

import jwt

DEFAULT_SECRETS_DIR = "/run/secrets/pack-credentials"


def slugify(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum()) or "pack"


def load_dispatch_secret(pack_name: str, secrets_dir: str | None = None) -> str | None:
    """Read this pack's dispatch secret from its mounted secret file."""
    directory = secrets_dir or os.getenv("PACK_SECRETS_DIR", DEFAULT_SECRETS_DIR)
    path = os.path.join(directory, f"{slugify(pack_name)}-dispatch")
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def bearer_from_headers(headers: Any) -> str | None:
    """Extract a Bearer token from any header mapping, None when absent."""
    value = headers.get("Authorization") if hasattr(headers, "get") else None
    if not value or not value.lower().startswith("bearer "):
        return None
    return value[7:].strip() or None


def verify_core_dispatch_token(
    token: str, *, expected_pack: str, key: str
) -> dict[str, Any]:
    """Verify a core→pack dispatch token; raises jwt.PyJWTError on failure."""
    return jwt.decode(
        token,
        key,
        algorithms=["HS256"],
        issuer="agentos-core",
        audience=f"pack:{expected_pack}",
    )


def legacy_internal_token_allowed() -> bool:
    """Transition flag: accept the shared X-Internal-Token (default True).

    Sprint 5.9.4 flips enforcement to JWT-only; production refuses to boot
    with the flag left on at the end of the sprint.
    """
    return os.getenv("LEGACY_INTERNAL_TOKEN", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
