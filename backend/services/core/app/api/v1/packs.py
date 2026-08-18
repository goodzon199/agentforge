from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.services.pack_service import PackError, PackService

router = APIRouter(prefix="/packs", tags=["packs"])

MANAGER_ROLES = frozenset({"owner", "admin"})


class ManifestPayload(BaseModel):
    base_url: str = Field(min_length=1, max_length=255)
    manifest: dict[str, Any]


def _require_manager(actor: User) -> None:
    if not actor.is_superuser and actor.role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Управление packs доступно владельцу или администратору.",
        )


def _service(db: Session) -> PackService:
    return PackService(db)


@router.get("")
def list_packs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    packs = _service(db).list()
    return {"packs": [_service(db).to_dict(p) for p in packs]}


@router.post("/discover")
def discover_packs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch manifests from every configured pack base URL (settings)."""
    _require_manager(user)
    results = _service(db).discover()
    return {"discovered": results}


@router.post("/register")
def register_pack(
    payload: ManifestPayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Register a pack from a submitted manifest (manual, offline fallback)."""
    _require_manager(user)
    try:
        pack = _service(db).register_manifest(payload.base_url, payload.manifest)
    except PackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _service(db).to_dict(pack)


@router.get("/{name}")
def get_pack(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return _service(db).to_dict(_service(db).get(name))
    except PackError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{name}/enable")
def enable_pack(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_manager(user)
    try:
        pack = _service(db).enable(name)
    except PackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _service(db).to_dict(pack)


@router.post("/{name}/disable")
def disable_pack(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_manager(user)
    pack = _service(db).disable(name)
    return _service(db).to_dict(pack)


@router.get("/{name}/healthcheck")
def healthcheck_pack(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        return _service(db).healthcheck(name)
    except PackError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
