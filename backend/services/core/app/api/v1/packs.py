from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.pack_permissions import CATALOG
from app.models import User
from app.services.audit_service import AuditService
from app.services.pack_identity_service import PackIdentityError, PackIdentityService
from app.services.pack_permission_service import (
    PackPermissionError,
    PackPermissionService,
)
from app.services.pack_service import PackError, PackService

router = APIRouter(prefix="/packs", tags=["packs"])

MANAGER_ROLES = frozenset({"owner", "admin"})


class PermissionActionPayload(BaseModel):
    """Grant/revoke request. ``company_id`` scopes the grant to a tenant."""

    company_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class ManifestPayload(BaseModel):
    base_url: str = Field(min_length=1, max_length=255)
    manifest: dict[str, Any]


class ConfigurePayload(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


def _require_manager(actor: User) -> None:
    if not actor.is_superuser and actor.role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Управление packs доступно владельцу или администратору.",
        )


def _require_permission_admin(actor: User) -> None:
    """Grant/revoke is stricter than pack management (sprint 5.9.2).

    Only the platform superuser or a tenant OWNER may decide rights —
    plain managers/admins cannot escalate a pack's powers.
    """
    if not actor.is_superuser and actor.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Выдача и отзыв разрешений доступны только владельцу.",
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


@router.post("/{name}/configure")
def configure_pack(
    name: str,
    payload: ConfigurePayload,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_manager(user)
    try:
        pack = _service(db).configure(name, payload.config)
    except PackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _service(db).to_dict(pack)


@router.post("/{name}/upgrade")
def upgrade_pack(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Run the pack's own migrations (alembic upgrade head on its DB)."""
    _require_manager(user)
    try:
        pack = _service(db).upgrade(name)
    except PackError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _service(db).to_dict(pack)


@router.delete("/{name}")
def uninstall_pack(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_manager(user)
    try:
        _service(db).uninstall(name)
    except PackError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "pack": name}


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


# --- Pack identity (sprint 5.9.1) -------------------------------------------


def _identity_service(db: Session):
    return PackIdentityService(db), AuditService(db)


def _identity_dict(identity) -> dict[str, Any]:
    return {
        "pack_id": identity.pack_id,
        "service_id": identity.service_id,
        "status": identity.status.value,
        "credential_version": identity.credential_version,
        "created_at": identity.created_at.isoformat() if identity.created_at else None,
        "rotated_at": identity.rotated_at.isoformat() if identity.rotated_at else None,
        "revoked_at": identity.revoked_at.isoformat() if identity.revoked_at else None,
        "last_authenticated_at": (
            identity.last_authenticated_at.isoformat()
            if identity.last_authenticated_at
            else None
        ),
    }


@router.get("/{name}/identity")
def get_pack_identity(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Identity metadata only — never secrets (hashes stay server-side)."""
    svc, _ = _identity_service(db)
    identity = svc.get(name)
    if identity is None:
        raise HTTPException(status_code=404, detail=f"У пака {name!r} нет identity.")
    return _identity_dict(identity)


@router.post("/{name}/identity/provision")
@router.post("/{name}/identity/rotate")
def provision_pack_identity(
    name: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Issue or rotate both secrets. Plaintext shown exactly once.

    The pack must re-read the mounted secret files and restart; the version
    bump invalidates every previously issued token immediately.
    """
    _require_manager(user)
    svc, audit = _identity_service(db)
    try:
        result = svc.provision(name)
    except PackIdentityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    action = "identity.rotate" if svc.get(name).rotated_at is not None else "identity.provisioned"
    audit.record(
        action=action,
        entity_type="pack_identity",
        entity_id=name,
        actor_type="user",
        detail={"credential_version": result["credential_version"]},
    )
    db.commit()
    return result


# --- Declared / granted permissions (sprint 5.9.2) ---------------------------


def _permission_service(db: Session) -> PackPermissionService:
    return PackPermissionService(db)


@router.get("/{name}/permissions")
def get_pack_permissions(
    name: str,
    company_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Declared vs granted vs effective vs pending for one pack.

    Without ``company_id`` the global (tenant-neutral) view is returned;
    with it, tenant-specific grants of that company are included.
    """
    _service(db).get(name)  # 404 when the pack is unknown
    snapshot = _permission_service(db).snapshot(name, tenant_id=company_id)
    if company_id is not None:
        snapshot["tenant_id"] = str(company_id)
    return snapshot


@router.post("/{name}/permissions/{permission}/grant")
def grant_pack_permission(
    name: str,
    permission: str,
    payload: PermissionActionPayload | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_permission_admin(user)
    _service(db).get(name)
    payload = payload or PermissionActionPayload()
    if permission not in CATALOG:
        raise HTTPException(
            status_code=422,
            detail=f"Неизвестное платформе разрешение {permission!r}.",
        )
    try:
        row = _permission_service(db).grant(
            name,
            permission,
            actor_id=user.id,
            tenant_id=payload.company_id,
            reason=payload.reason,
        )
    except PackPermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {
        "pack": name,
        "permission": row.permission,
        "status": row.status,
        "grant_source": row.grant_source,
        "company_id": str(row.tenant_id) if row.tenant_id else None,
    }


@router.post("/{name}/permissions/{permission}/revoke")
def revoke_pack_permission(
    name: str,
    permission: str,
    payload: PermissionActionPayload | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    _require_permission_admin(user)
    _service(db).get(name)
    payload = payload or PermissionActionPayload()
    try:
        row = _permission_service(db).revoke(
            name,
            permission,
            actor_id=user.id,
            tenant_id=payload.company_id,
            reason=payload.reason,
        )
    except PackPermissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return {
        "pack": name,
        "permission": row.permission,
        "status": row.status,
        "company_id": str(row.tenant_id) if row.tenant_id else None,
    }
