"""Internal-HTTP client for the core <-> autoparts contract.

Token-gated with ``INTERNAL_API_TOKEN``. Both services expose internal routes
under ``/internal/*`` and require the ``X-Internal-Token`` header. The client
is a thin httpx wrapper that raises on non-2xx.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import HTTPException, Request, status

_INTERNAL_TOKEN_ENV = "INTERNAL_API_TOKEN"
_DEFAULT_TOKEN = "dev-internal-token-change-me"


def internal_token() -> str:
    return os.getenv(_INTERNAL_TOKEN_ENV, _DEFAULT_TOKEN)


def internal_headers() -> dict[str, str]:
    return {"X-Internal-Token": internal_token()}


def internal_post(
    base_url: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 30.0,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers = internal_headers()
    if extra_headers:
        headers.update(extra_headers)
    resp = httpx.post(
        f"{base_url.rstrip('/')}{path}",
        json=payload or {},
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def internal_get(base_url: str, path: str, *, timeout: float = 20.0) -> dict[str, Any]:
    resp = httpx.get(
        f"{base_url.rstrip('/')}{path}",
        headers=internal_headers(),
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


# --- Server side -----------------------------------------------------------

def is_internal_request(headers: Any, token: str | None = None) -> bool:
    """True when the request carries a valid internal token.

    ``headers`` is any object exposing ``.get(name)`` (e.g. Starlette Headers
    or a plain dict). The expected token comes from ``INTERNAL_API_TOKEN``
    unless overridden.
    """
    expected = token if token is not None else internal_token()
    provided = headers.get("X-Internal-Token") if hasattr(headers, "get") else None
    return bool(expected) and provided == expected


def require_internal_token(request: Request) -> None:
    """FastAPI dependency guarding /internal/* routes.

    Rejects requests without the shared internal token.
    """
    if not is_internal_request(request.headers):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный внутренний токен.",
        )


def require_core_dispatch(request: Request, *, pack_name: str) -> None:
    """Transitional core→pack auth for agent execution (sprint 5.9.1).

    When the request carries ``Authorization: Bearer`` it MUST be a valid
    dispatch token signed with THIS pack's own secret (aud=pack:<name>) —
    another pack's token fails the audience check. Without a bearer token
    the legacy shared token path stays available while
    ``LEGACY_INTERNAL_TOKEN=true``; sprint 5.9.4 flips this to JWT-only.
    """
    import jwt

    from shared.pack_security import (
        bearer_from_headers,
        legacy_internal_token_allowed,
        load_dispatch_secret,
        verify_core_dispatch_token,
    )

    token = bearer_from_headers(request.headers)
    if token is None:
        if legacy_internal_token_allowed():
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PACK_UNAUTHENTICATED: требуется Bearer dispatch token.",
        )
    secret = load_dispatch_secret(pack_name)
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="PACK_UNAUTHENTICATED: dispatch secret не смонтирован.",
        )
    try:
        verify_core_dispatch_token(token, expected_pack=pack_name, key=secret)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"PACK_UNAUTHENTICATED: неверный dispatch token ({exc}).",
        ) from exc
