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


def internal_post(base_url: str, path: str, *, payload: dict[str, Any] | None = None, timeout: float = 30.0) -> dict[str, Any]:
    resp = httpx.post(
        f"{base_url.rstrip('/')}{path}",
        json=payload or {},
        headers=internal_headers(),
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
