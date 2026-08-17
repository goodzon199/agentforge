from __future__ import annotations

"""Internal-HTTP client for the core <-> autoparts contract.

Token-gated with ``INTERNAL_API_TOKEN``. Both services expose internal routes
under ``/internal/*`` and require the ``X-Internal-Token`` header. The client
is a thin httpx wrapper that raises on non-2xx.
"""

import os
from typing import Any

import httpx

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