from __future__ import annotations

import logging
from typing import Any, ClassVar

import httpx
from shared.internal import internal_headers
from shared.pack import (
    ManifestError,
    PackManifest,
    PackState,
    parse_manifest,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Pack

logger = logging.getLogger(__name__)


class PackError(RuntimeError):
    """Raised when a pack cannot be discovered/validated/registered."""


class PackService:
    """Pack registry operations (sprint 5.1).

    Core never imports pack code: it reads a pack's manifest over the
    internal HTTP contract, validates it with the shared SDK, stores the
    contract in the ``packs`` table and tracks the lifecycle state. Agents,
    workflows and migrations live in the pack service itself.
    """

    def __init__(self, db: Session):
        self.db = db

    # --- Discovery ----------------------------------------------------------

    def discover(self) -> list[dict[str, Any]]:
        """Fetch manifests from every configured pack base URL and upsert."""
        results: list[dict[str, Any]] = []
        for base_url in settings.pack_base_urls:
            results.append(self.discover_one(base_url))
        return results

    def discover_one(self, base_url: str) -> dict[str, Any]:
        try:
            manifest = self._fetch_manifest(base_url)
            pack = self.register(base_url, manifest)
            return {"pack": pack.name, "version": pack.version, "ok": True}
        except (PackError, ManifestError, httpx.HTTPError) as exc:
            logger.warning("discover failed for %s: %s", base_url, exc)
            return {"pack": base_url, "ok": False, "error": str(exc)}

    # --- Manifest fetch / validate -----------------------------------------

    def _fetch_manifest(self, base_url: str) -> PackManifest:
        resp = httpx.get(
            f"{base_url.rstrip('/')}/internal/pack/manifest",
            headers=internal_headers(),
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if "manifest" not in data:
            raise PackError("pack /internal/pack/manifest не вернул поле manifest.")
        return parse_manifest(data["manifest"])

    def validate(self, base_url: str, manifest: PackManifest) -> list[str]:
        """Validate a manifest against the SDK + core compatibility.

        Returns a list of warnings; raises PackError on hard failures.
        """
        problems: list[str] = []
        if not manifest.agents:
            problems.append("pack не объявляет агентов")
        if not manifest.check_core_compatible(settings.core_version):
            raise PackError(
                f"pack требует core {manifest.required_core_version}, "
                f"а установлен {settings.core_version}"
            )
        return problems

    # --- Registration ------------------------------------------------------

    def register(self, base_url: str, manifest: PackManifest) -> Pack:
        """Upsert a pack from its manifest (state=installed on create)."""
        warnings = self.validate(base_url, manifest)
        existing = self.db.scalars(
            select(Pack).where(Pack.name == manifest.name)
        ).first()

        if existing is None:
            pack = Pack(
                name=manifest.name,
                version=manifest.version,
                display_name=manifest.display_name,
                description=manifest.description,
                base_url=base_url,
                required_core_version=manifest.required_core_version,
                manifest=manifest.model_dump(mode="json"),
                agents=manifest.model_dump(mode="json")["agents"],
                permissions=manifest.permissions,
                workflows=manifest.model_dump(mode="json")["workflows"],
                tools=manifest.tools,
                state=PackState.installed,
                is_active=False,
            )
            self.db.add(pack)
        else:
            # New manifest seen -> require an explicit upgrade step (5.2).
            if existing.version != manifest.version:
                existing.state = PackState.upgrade_required
            existing.version = manifest.version
            existing.display_name = manifest.display_name
            existing.description = manifest.description
            existing.base_url = base_url
            existing.required_core_version = manifest.required_core_version
            existing.manifest = manifest.model_dump(mode="json")
            existing.agents = manifest.model_dump(mode="json")["agents"]
            existing.permissions = manifest.permissions
            existing.workflows = manifest.model_dump(mode="json")["workflows"]
            existing.tools = manifest.tools
            pack = existing

        self.db.commit()
        self.db.refresh(pack)
        for warning in warnings:
            logger.info("pack %s warning: %s", manifest.name, warning)
        return pack

    def register_manifest(self, base_url: str, manifest_data: dict[str, Any]) -> Pack:
        """Register from raw manifest content (manual register endpoint)."""
        try:
            manifest = parse_manifest(manifest_data)
        except ManifestError as exc:
            raise PackError(str(exc)) from exc
        return self.register(base_url, manifest)

    # --- Lifecycle ---------------------------------------------------------

    # Allowed transitions per operation. ``*`` = any state.
    _TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        "install": {"*"},
        "configure": {"installed", "upgrade_required", "degraded", "disabled"},
        "enable": {"installed", "configured", "degraded", "disabled", "upgrade_required"},
        "disable": {"active", "degraded", "configured", "upgrade_required"},
        "upgrade": {"installed", "configured", "active", "degraded", "disabled", "upgrade_required"},
        "uninstall": {"*"},
    }

    def _guard(self, pack: Pack, operation: str) -> None:
        allowed = self._TRANSITIONS[operation]
        if "*" not in allowed and pack.state.value not in allowed:
            raise PackError(
                f"Pack {pack.name!r} в состоянии {pack.state.value} "
                f"нельзя {operation}."
            )

    def get(self, name: str) -> Pack:
        pack = self.db.scalars(select(Pack).where(Pack.name == name)).first()
        if pack is None:
            raise PackError(f"Pack {name!r} не зарегистрирован.")
        return pack

    def list(self) -> list[Pack]:
        return list(self.db.scalars(select(Pack).order_by(Pack.name)))

    def configure(self, name: str, config: dict[str, Any]) -> Pack:
        pack = self.get(name)
        self._guard(pack, "configure")
        pack.config = config or {}
        pack.state = PackState.configured
        self.db.commit()
        self.db.refresh(pack)
        return pack

    def enable(self, name: str) -> Pack:
        pack = self.get(name)
        self._guard(pack, "enable")
        # Live health gate before activation.
        ok = self._probe_health(pack.base_url)
        if not ok:
            pack.state = PackState.degraded
            self.db.commit()
            raise PackError(f"Pack {name!r} недоступен (healthcheck не прошёл).")
        pack.is_active = True
        pack.state = PackState.active
        self.db.commit()
        self.db.refresh(pack)
        return pack

    def disable(self, name: str) -> Pack:
        pack = self.get(name)
        self._guard(pack, "disable")
        pack.is_active = False
        pack.state = PackState.disabled
        self.db.commit()
        self.db.refresh(pack)
        return pack

    def upgrade(self, name: str) -> Pack:
        """Apply the pack's own migrations, then mark it ready (configured).

        Fetches the current manifest, POSTs /internal/pack/migrate so the
        pack runs ``alembic upgrade head`` on its own DB, then records the
        revision. A pack in ``upgrade_required`` (new manifest version seen
        at register) lands back in ``configured``; an active pack is kept
        running (migrations are additive).
        """
        pack = self.get(name)
        self._guard(pack, "upgrade")
        try:
            resp = httpx.post(
                f"{pack.base_url.rstrip('/')}/internal/pack/migrate",
                headers=internal_headers(),
                timeout=60.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise PackError(
                f"migrate pack {name!r} не удался: {exc}"
            ) from exc

        revision = data.get("revision")
        logger.info("pack %s migrated to %s", name, revision)
        if not pack.is_active:
            pack.state = PackState.configured
        self.db.commit()
        self.db.refresh(pack)
        return pack

    def uninstall(self, name: str) -> None:
        pack = self.get(name)
        self._guard(pack, "uninstall")
        self.db.delete(pack)
        self.db.commit()

    def healthcheck(self, name: str) -> dict[str, Any]:
        pack = self.get(name)
        ok = self._probe_health(pack.base_url)
        from datetime import UTC, datetime

        pack.last_healthcheck_at = datetime.now(UTC)
        pack.last_health_ok = ok
        if not ok and pack.is_active:
            pack.state = PackState.degraded
        if ok and pack.state == PackState.degraded and pack.is_active:
            pack.state = PackState.active
        self.db.commit()
        return {"pack": pack.name, "health": "ok" if ok else "down"}

    def _probe_health(self, base_url: str) -> bool:
        try:
            resp = httpx.get(
                f"{base_url.rstrip('/')}/internal/health",
                headers=internal_headers(),
                timeout=5.0,
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    def to_dict(self, pack: Pack) -> dict[str, Any]:
        return {
            "id": str(pack.id),
            "name": pack.name,
            "version": pack.version,
            "display_name": pack.display_name,
            "description": pack.description,
            "base_url": pack.base_url,
            "required_core_version": pack.required_core_version,
            "state": pack.state.value,
            "is_active": pack.is_active,
            "agents": pack.agents,
            "permissions": pack.permissions,
            "workflows": pack.workflows,
            "tools": pack.tools,
            "last_healthcheck_at": (
                pack.last_healthcheck_at.isoformat() if pack.last_healthcheck_at else None
            ),
            "last_health_ok": pack.last_health_ok,
            "config": pack.config or {},
        }
