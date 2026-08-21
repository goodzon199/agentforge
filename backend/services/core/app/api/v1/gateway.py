from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Pack

logger = logging.getLogger(__name__)

router = APIRouter(tags=["gateway"])

# Browser-facing headers we forward to the pack. Hop-by-hop headers (Host,
# Content-Length, Connection) are excluded — httpx rebuilds them.
_FORWARD_HEADERS = frozenset(
    {
        "authorization",
        "content-type",
        "accept",
        "accept-language",
        "x-correlation-id",
        "x-request-id",
    }
)

# Core's own API surface that must never fall into a pack route (they are
# registered before the gateway, so this list is a safety net only).
_CORE_RESERVED_PREFIXES = frozenset(
    {"/packs", "/platform", "/auth", "/conversations", "/customers", "/tasks"}
)


def _route_prefix(prefix: str) -> str:
    return f"/{prefix.lstrip('/')}"


def _resolve_pack(db: Session, prefix: str) -> Pack | None:
    """Find an active pack exposing the given gateway prefix."""
    route = _route_prefix(prefix)
    packs = db.scalars(select(Pack).where(Pack.is_active.is_(True))).all()
    for pack in packs:
        for declared in pack.routes or []:
            if declared.get("prefix") == route:
                return pack
    return None


@router.api_route("/{prefix}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(
    prefix: str,
    path: str,
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    """Platform gateway: route /api/v1{route.prefix}/... to the owning pack.

    The frontend knows a single core address; the registry maps a public
    namespace (e.g. /autoparts) to the pack's own service, so installing a
    pack automatically exposes its API without frontend changes.
    """
    route = _route_prefix(prefix)
    if route in _CORE_RESERVED_PREFIXES:
        raise HTTPException(status_code=404, detail="Маршрут не найден.")

    pack = _resolve_pack(db, prefix)
    if pack is None:
        raise HTTPException(status_code=404, detail="Маршрут не найден.")

    base = pack.base_url.rstrip("/")
    target = f"{base}/api/v1/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in _FORWARD_HEADERS
    }
    body = await request.body()

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.request(
                request.method,
                target,
                headers=headers,
                content=body if body else None,
                follow_redirects=False,
            )
    except httpx.HTTPError as exc:
        logger.warning("gateway %s -> %s failed: %s", route, target, exc)
        raise HTTPException(status_code=502, detail="Шлюз недоступен.") from exc

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type"),
        headers=_passthrough_headers(resp),
    )


def _passthrough_headers(resp: httpx.Response) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("content-type", "x-request-id", "x-correlation-id"):
        value = resp.headers.get(name)
        if value:
            out[name] = value
    return out
