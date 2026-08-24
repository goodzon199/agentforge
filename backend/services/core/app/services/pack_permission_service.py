from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pack_permissions import CATALOG, risk_of, unknown_permissions
from app.models import (
    PackDeclaredPermission,
    PackGrantSource,
    PackGrantStatus,
    PackPermissionGrant,
)
from app.services.audit_service import AuditService


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class PackPermissionError(Exception):
    """Raised when grant/revoke preconditions are violated."""


class PackPermissionService:
    """Declared vs granted permission lifecycle (sprint 5.9.2).

    Invariant: ``effective = declared ∩ granted``. The manifest only
    declares requests; rights exist solely as admin-issued grants keyed by
    ``(tenant_id, pack_id, permission)`` with ``tenant_id IS NULL`` for
    global grants.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- queries ------------------------------------------------------------

    def declared(self, pack_id: str) -> set[str]:
        rows = self.db.scalars(
            select(PackDeclaredPermission).where(
                PackDeclaredPermission.pack_id == pack_id,
                PackDeclaredPermission.removed_at.is_(None),
            )
        ).all()
        return {r.permission for r in rows}

    def _grant_rows(self, pack_id: str) -> list[PackPermissionGrant]:
        return list(
            self.db.scalars(
                select(PackPermissionGrant).where(
                    PackPermissionGrant.pack_id == pack_id
                )
            ).all()
        )

    def effective(self, pack_id: str, tenant_id: uuid.UUID | None = None) -> set[str]:
        """Active grants that matter for a tenant, intersected with declared.

        ``tenant_id=None`` → global grants only. A concrete tenant inherits
        global grants plus its own.
        """
        declared = self.declared(pack_id)
        granted: set[str] = set()
        for row in self._grant_rows(pack_id):
            if row.status != PackGrantStatus.active.value:
                continue
            if row.tenant_id is None or (tenant_id is not None and row.tenant_id == tenant_id):
                granted.add(row.permission)
        return declared & granted

    def pending(self, pack_id: str, tenant_id: uuid.UUID | None = None) -> set[str]:
        return self.declared(pack_id) - self.effective(pack_id, tenant_id)

    def snapshot(self, pack_id: str, tenant_id: uuid.UUID | None = None) -> dict[str, Any]:
        declared = sorted(self.declared(pack_id))
        effective = sorted(self.effective(pack_id, tenant_id))
        pending = sorted(self.pending(pack_id, tenant_id))
        return {
            "pack": pack_id,
            "declared": declared,
            "granted": effective,
            "effective": effective,
            "pending": pending,
            "tenant_scoped": tenant_id is not None,
        }

    # --- manifest sync (register/upgrade hook) -------------------------------

    def sync_declared(self, pack_id: str, permissions: list[str], manifest_version: str) -> dict[str, list[str]]:
        """Align the declared projection and grant statuses with a manifest.

        Returns the diff for logging: added / removed / auto_restored /
        awaiting_review permission names.
        """
        unknown = unknown_permissions(permissions)
        if unknown:
            raise PackPermissionError(
                f"Манифест заявляет неизвестные платформе разрешения: {', '.join(sorted(unknown))}."
            )

        now = _now()
        existing_rows = {
            r.permission: r
            for r in self.db.scalars(
                select(PackDeclaredPermission).where(
                    PackDeclaredPermission.pack_id == pack_id
                )
            ).all()
        }
        active_declared = {
            name for name, row in existing_rows.items() if row.removed_at is None
        }
        new_perms = set(permissions or [])
        added = new_perms - active_declared
        removed = active_declared - new_perms

        for perm in sorted(added):
            row = existing_rows.get(perm)
            if row is not None:  # re-declared after removal
                row.removed_at = None
                row.manifest_version = manifest_version
                row.declared_at = now
            else:
                self.db.add(
                    PackDeclaredPermission(
                        pack_id=pack_id,
                        permission=perm,
                        manifest_version=manifest_version,
                        declared_at=now,
                    )
                )
        for perm in sorted(removed):
            row = existing_rows[perm]
            row.removed_at = now
            # Grants stop counting immediately but stay for history/review.
            for grant in self._grant_rows(pack_id):
                if grant.permission == perm and grant.status == PackGrantStatus.active.value:
                    grant.status = PackGrantStatus.inactive_not_declared.value

        # Permissions returning to the manifest: LOW/MEDIUM grants are
        # restored; HIGH-risk always requires explicit re-review by an admin.
        auto_restored: list[str] = []
        awaiting_review: list[str] = []
        for perm in sorted(added):
            for grant in self._grant_rows(pack_id):
                if grant.permission != perm:
                    continue
                if grant.status == PackGrantStatus.inactive_not_declared.value:
                    if risk_of(perm) == "HIGH":
                        awaiting_review.append(perm)
                    else:
                        grant.status = PackGrantStatus.active.value
                        auto_restored.append(perm)
                    break

        if added:
            self._audit(pack_id, "pack.permission.requested",
                        detail={"permissions": sorted(added), "manifest_version": manifest_version})
        if removed:
            self._audit(pack_id, "pack.permission.removed_from_manifest",
                        detail={"permissions": sorted(removed), "manifest_version": manifest_version})
        for perm in auto_restored:
            self._audit(pack_id, "pack.permission.granted",
                        detail={"permission": perm, "reason": "restored_after_redeclare",
                                "manifest_version": manifest_version})

        return {
            "added": sorted(added),
            "removed": sorted(removed),
            "auto_restored": auto_restored,
            "awaiting_review": sorted(set(awaiting_review)),
        }

    # --- bootstrap -----------------------------------------------------------

    def bootstrap_builtin(self) -> dict[str, int]:
        """One-time transfer declared -> granted for trusted builtin packs.

        Mirrors the data step of migration e8f21b4c6a93 for databases where
        packs already existed when it ran (idempotent: skips packs that
        already hold any grants).
        """
        from app.core.pack_permissions import BUILTIN_BOOTSTRAP_PACKS
        from app.models import Pack

        result: dict[str, int] = {}
        for name in sorted(BUILTIN_BOOTSTRAP_PACKS):
            pack = self.db.scalars(select(Pack).where(Pack.name == name)).first()
            if pack is None or self._grant_rows(name):
                continue
            count = 0
            for perm in pack.permissions or []:
                self.db.add(self._new_grant(
                    name, perm, source=PackGrantSource.migration_bootstrap.value
                ))
                count += 1
            result[name] = count
        self.db.flush()
        return result

    @staticmethod
    def _new_grant(
        pack_id: str,
        permission: str,
        *,
        source: str,
        actor_id: uuid.UUID | None = None,
        tenant_id: uuid.UUID | None = None,
    ) -> PackPermissionGrant:
        return PackPermissionGrant(
            pack_id=pack_id,
            tenant_id=tenant_id,
            permission=permission,
            status=PackGrantStatus.active.value,
            grant_source=source,
            granted_by_user_id=actor_id,
            granted_at=_now(),
        )

    # --- admin operations -----------------------------------------------------

    def grant(
        self,
        pack_id: str,
        permission: str,
        *,
        actor_id: uuid.UUID | None,
        tenant_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> PackPermissionGrant:
        spec = CATALOG.get(permission)
        if spec is None:
            raise PackPermissionError(f"Неизвестное разрешение {permission!r}.")
        if permission not in self.declared(pack_id):
            raise PackPermissionError(
                f"Разрешение {permission!r} не заявлено в манифесте пака — выдавать нечего."
            )

        row = self._find_grant(pack_id, permission, tenant_id)
        if row is not None and row.status == PackGrantStatus.active.value:
            return row  # idempotent re-grant

        if row is None:
            row = self._new_grant(pack_id, permission, source="admin", actor_id=actor_id, tenant_id=tenant_id)
            self.db.add(row)
        else:  # revoked or inactive_not_declared -> explicit admin decision
            row.status = PackGrantStatus.active.value
            row.grant_source = PackGrantSource.admin.value
            row.granted_by_user_id = actor_id
            row.granted_at = _now()
            row.revoked_by_user_id = None
            row.revoked_at = None
        self.db.flush()

        self._audit(
            pack_id, "pack.permission.granted",
            actor_id=actor_id,
            detail={"permission": permission, "risk_level": spec.risk_level.value,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "reason": reason or ("re_review" if spec.risk_level.value == "HIGH" else "admin_decision")},
        )
        return row

    def revoke(
        self,
        pack_id: str,
        permission: str,
        *,
        actor_id: uuid.UUID | None,
        tenant_id: uuid.UUID | None = None,
        reason: str | None = None,
    ) -> PackPermissionGrant:
        row = self._find_grant(pack_id, permission, tenant_id)
        if row is None or row.status != PackGrantStatus.active.value:
            raise PackPermissionError(
                f"Активный грант {permission!r} для пака {pack_id!r} не найден."
            )
        row.status = PackGrantStatus.revoked.value
        row.revoked_by_user_id = actor_id
        row.revoked_at = _now()
        self.db.flush()

        self._audit(
            pack_id, "pack.permission.revoked",
            actor_id=actor_id,
            detail={"permission": permission,
                    "tenant_id": str(tenant_id) if tenant_id else None,
                    "reason": reason},
        )
        return row

    def _find_grant(
        self, pack_id: str, permission: str, tenant_id: uuid.UUID | None
    ) -> PackPermissionGrant | None:
        for row in self._grant_rows(pack_id):
            if row.permission == permission and row.tenant_id == tenant_id:
                return row
        return None

    # --- audit -----------------------------------------------------------------

    def _audit(
        self,
        pack_id: str,
        action: str,
        *,
        actor_id: uuid.UUID | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        # AuditService fills ip/request_id/actor from the request context.
        AuditService(self.db).record(
            action=action,
            entity_type="pack_permissions",
            entity_id=pack_id,
            user_id=actor_id,
            actor_type="system" if actor_id is None else "user",
            detail=detail or {},
        )
