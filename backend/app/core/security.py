from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings

_PBKDF2_ITERATIONS = 100_000

_DEFAULT_JWT_SECRET = "dev-only-agentforge-jwt-secret-change-me-9f3a1c"
_DEFAULT_ADMIN_PASSWORD = "admin123"

# Well-known / placeholder passwords that must never be accepted, in any
# environment, when set as the bootstrap admin password.
_FORBIDDEN_ADMIN_PASSWORDS = frozenset(
    {"admin123", "password", "12345678", "changeme", "change-me-please"}
)


def validate_production_settings() -> None:
    """Fail fast on insecure configuration in production.

    Development keeps permissive defaults; production refuses to start with
    the well-known dev secret, a non-Postgres database, debug mode on, schema
    auto-creation enabled, or a missing / well-known bootstrap admin password.
    """
    if settings.environment != "production":
        return
    if settings.jwt_secret == _DEFAULT_JWT_SECRET or len(settings.jwt_secret) < 32:
        raise RuntimeError(
            "Production startup blocked: JWT_SECRET must be a fresh secret "
            "of at least 32 characters (not the development default)."
        )
    if not settings.database_url.startswith("postgres"):
        raise RuntimeError(
            "Production startup blocked: DATABASE_URL must point to PostgreSQL."
        )
    if settings.debug:
        raise RuntimeError("Production startup blocked: DEBUG must be False.")
    if settings.db_auto_create:
        raise RuntimeError(
            "Production startup blocked: DB_AUTO_CREATE must be False "
            "(schema is managed by Alembic only)."
        )
    if not settings.seed_admin_password:
        raise RuntimeError(
            "Production startup blocked: SEED_ADMIN_PASSWORD is required "
            "for the bootstrap admin account."
        )
    if settings.seed_admin_password in _FORBIDDEN_ADMIN_PASSWORDS:
        raise RuntimeError(
            "Production startup blocked: SEED_ADMIN_PASSWORD is a well-known "
            "value and must be replaced with a strong password."
        )
    if len(settings.seed_admin_password) < settings.min_password_length:
        raise RuntimeError(
            "Production startup blocked: SEED_ADMIN_PASSWORD must be at least "
            f"{settings.min_password_length} characters."
        )
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if not origins or "*" in origins:
        raise RuntimeError(
            "Production startup blocked: CORS_ORIGINS must be an explicit "
            "list of allowed origins (a bare wildcard is refused)."
        )
    if not settings.openai_api_key:
        raise RuntimeError(
            "Production startup blocked: OPENAI_API_KEY is required "
            "(set it even for a local model endpoint)."
        )


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 (salt per user)."""
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2:sha256:{_PBKDF2_ITERATIONS}${salt}${digest}"


def validate_password_strength(password: str) -> None:
    """Raise ValueError when the password is too short (configurable minimum)."""
    if len(password) < settings.min_password_length:
        raise ValueError(
            f"Пароль должен быть не короче {settings.min_password_length} символов."
        )


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time password check against a stored PBKDF2 hash."""
    try:
        _, _, rest = hashed.split(":", 2)
        iterations, salt, digest = rest.split("$")
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str) -> str:
    """Issue a signed JWT for a user id."""
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iss": settings.jwt_issuer,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    """Validate a JWT and return the user id. None on any failure."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
        )
        if payload.get("type") != "access":
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
