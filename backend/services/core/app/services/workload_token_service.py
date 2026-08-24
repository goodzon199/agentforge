"""Workload token lifecycle (sprint 5.9.3, contract 5A).

Minting is exclusive to Core at dispatch time; verification implements the
full pipeline from 5A.5 and returns a ``PackWorkloadPrincipal``. Denials are
audited as ``pack.workload.denied`` with a structured reason.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.workload import (
    TOKEN_TYPE_WORKLOAD,
    PackWorkloadPrincipal,
    WorkloadDenyReason,
    WorkloadScope,
    WorkloadTokenError,
    required_permissions_for,
    tenant_scope_allowed,
)
from app.models import PackDispatch, PackDispatchStatus, PackIdentity, PackIdentityStatus
from app.services.audit_service import AuditService
from app.services.pack_permission_service import PackPermissionService

logger = logging.getLogger(__name__)

_ISSUER = "agentos-core"
_AUDIENCE = "agentos-internal"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class WorkloadVerificationError(Exception):
    """Raised when a workload token fails any pipeline check (5A.5)."""

    def __init__(
        self,
        reason: WorkloadDenyReason,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.detail = detail or {}


class WorkloadTokenService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # --- issuance (Core only) --------------------------------------------------

    def issue(
        self,
        *,
        pack_id: str,
        tenant_id: str | None,
        task_id: str | None,
        dispatch_id: str,
        operation: str,
        scope_mode: str = "explicit",
        scope: WorkloadScope | None = None,
        task_deadline: dt.datetime | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Mint a workload token; returns (token, claims).

        Fail-closed paths (I2/I3/I4): unknown operation, tenant-scope for an
        operation outside the allowlist, deadline already passed.
        """
        required = required_permissions_for(operation)  # I2: raises when unknown
        if scope_mode == "tenant" and not tenant_scope_allowed(operation):  # I3
            raise WorkloadTokenError(
                f"Операция {operation!r} не входит в TENANT_SCOPE_OPERATIONS — "
                "scope_mode=tenant запрещён."
            )
        now = _now()
        if task_deadline is not None:
            if task_deadline.tzinfo is None:
                task_deadline = task_deadline.replace(tzinfo=dt.UTC)
            if task_deadline <= now:  # I4: no token for an expired task
                raise WorkloadTokenError(
                    "Дедлайн задачи уже истек — workload token не выпускается."
                )

        effective: set[str] = set()
        if tenant_id:
            effective = PackPermissionService(self.db).effective(pack_id, _uuid_or_none(tenant_id))
        else:
            effective = PackPermissionService(self.db).effective(pack_id)
        permissions = sorted(required & effective)

        ttl = settings.workload_jwt_ttl_seconds
        exp = now + dt.timedelta(seconds=ttl)
        if task_deadline is not None and task_deadline < exp:  # I4 cap
            exp = task_deadline

        resolved_scope = scope or (
            WorkloadScope(mode="tenant")
            if scope_mode == "tenant"
            else WorkloadScope()
        )
        jti = uuid.uuid4().hex
        claims: dict[str, Any] = {
            "iss": _ISSUER,
            "sub": f"pack:{pack_id}",
            "aud": _AUDIENCE,
            "token_type": TOKEN_TYPE_WORKLOAD,
            "pack_id": pack_id,
            "jti": jti,
            "iat": now,
            "nbf": now,
            "exp": exp,
            "credential_version": self._credential_version_of(pack_id),
            "permissions": permissions,
            "scope": resolved_scope.to_claims(),
            "operation": operation,
        }
        if tenant_id:
            claims["tenant_id"] = tenant_id
        if task_id:
            claims["task_id"] = task_id
        claims["dispatch_id"] = dispatch_id

        token = jwt.encode(claims, settings.internal_jwt_key, algorithm="HS256")
        return token, claims

    def record_dispatch(
        self,
        *,
        dispatch_id: str,
        pack_id: str,
        operation: str,
        jti: str,
        task_id: str | None = None,
        company_id: str | None = None,
        replayed_from: str | None = None,
    ) -> PackDispatch:
        """Persist the active-dispatch binding, superseding prior ones."""
        if replayed_from and task_id:
            self.supersede_task_dispatches(task_id)
        row = PackDispatch(
            dispatch_id=dispatch_id,
            pack_id=pack_id,
            task_id=uuid.UUID(task_id) if task_id else None,
            company_id=uuid.UUID(company_id) if company_id else None,
            operation=operation,
            workload_jti=jti,
            status=PackDispatchStatus.active,
            replayed_from=uuid.UUID(replayed_from) if replayed_from else None,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def supersede_task_dispatches(self, task_id: str) -> int:
        rows = self.db.scalars(
            select(PackDispatch).where(
                PackDispatch.task_id == uuid.UUID(task_id),
                PackDispatch.status == PackDispatchStatus.active,
            )
        ).all()
        for row in rows:
            row.status = PackDispatchStatus.superseded
        return len(rows)

    def mark_task_dispatches_terminal(
        self, task_id: str, *, failed: bool = False
    ) -> None:
        """Flip active dispatches of a finished task to completed/failed."""
        target = (
            PackDispatchStatus.failed if failed else PackDispatchStatus.completed
        )
        rows = self.db.scalars(
            select(PackDispatch).where(
                PackDispatch.task_id == uuid.UUID(task_id),
                PackDispatch.status == PackDispatchStatus.active,
            )
        ).all()
        for row in rows:
            row.status = target
            row.finished_at = _now()

    # --- revocation kill-switch (best-effort Redis denylist) --------------------

    def revoke_jti(self, jti: str, *, ttl_seconds: int | None = None) -> bool:
        from app.core.redis import redis_client

        if not redis_client.available:
            logger.warning("jti denylist unavailable — token %s stays valid", jti)
            return False
        redis_client.set_json(f"workload:jti:{jti}", 1, ttl_seconds or settings.workload_jwt_ttl_seconds)
        return True

    def _jti_revoked(self, jti: str) -> bool:
        from app.core.redis import redis_client

        if not redis_client.available:
            return False
        return redis_client.get_json(f"workload:jti:{jti}") is not None

    # --- verification pipeline (5A.5) ---------------------------------------------

    def verify(self, token: str) -> PackWorkloadPrincipal:
        leeway = settings.workload_clock_skew_seconds
        try:
            claims = jwt.decode(
                token,
                settings.internal_jwt_key,
                algorithms=["HS256"],
                issuer=_ISSUER,
                audience=_AUDIENCE,
                leeway=leeway,
            )
        except jwt.PyJWTError as exc:
            raise WorkloadVerificationError(
                WorkloadDenyReason.token_invalid, f"Невалидный workload token: {exc}"
            ) from exc

        def _fail(reason: WorkloadDenyReason, message: str):
            partial = {
                key: str(claims[key])
                for key in ("pack_id", "tenant_id", "task_id", "dispatch_id", "jti")
                if claims.get(key)
            }
            raise WorkloadVerificationError(reason, message, detail=partial)

        if claims.get("token_type") != TOKEN_TYPE_WORKLOAD:  # I1
            _fail(
                WorkloadDenyReason.token_invalid,
                "token_type != workload — Context API принимает только workload-токены.",
            )
        missing = {
            name
            for name in ("pack_id", "tenant_id", "task_id", "dispatch_id", "jti")
            if not claims.get(name)
        }
        if missing:
            _fail(
                WorkloadDenyReason.token_invalid,
                f"Отсутствуют обязательные claims: {', '.join(sorted(missing))}.",
            )

        identity = self.db.scalars(
            select(PackIdentity).where(PackIdentity.pack_id == claims["pack_id"])
        ).first()
        if identity is None:
            _fail(
                WorkloadDenyReason.identity_missing,
                f"Identity пака {claims['pack_id']!r} не найдена.",
            )
        if identity.status == PackIdentityStatus.disabled:
            _fail(WorkloadDenyReason.identity_disabled, "PACK_DISABLED.")
        if identity.status == PackIdentityStatus.revoked:
            _fail(WorkloadDenyReason.identity_disabled, "PACK_REVOKED.")
        if claims.get("credential_version") != identity.credential_version:
            _fail(
                WorkloadDenyReason.credential_version_mismatch,
                "credential_version токена не совпадает с текущей ротацией.",
            )

        dispatch = self.db.scalars(
            select(PackDispatch).where(
                PackDispatch.dispatch_id == claims["dispatch_id"]
            )
        ).first()
        if dispatch is None or dispatch.status != PackDispatchStatus.active:
            _fail(
                WorkloadDenyReason.token_revoked,
                "Dispatch не активен (завершён, провален или заменён при replay).",
            )
        if self._jti_revoked(str(claims["jti"])):
            _fail(WorkloadDenyReason.token_revoked, "jti в denylist.")

        scope = WorkloadScope.from_claims(claims)
        if scope.mode == "tenant" and not tenant_scope_allowed(
            str(dispatch.operation)
        ):
            _fail(
                WorkloadDenyReason.token_invalid,
                "scope_mode=tenant недопустим для этой операции.",
            )

        return PackWorkloadPrincipal(
            pack_id=str(claims["pack_id"]),
            tenant_id=str(claims["tenant_id"]),
            task_id=str(claims["task_id"]),
            dispatch_id=str(claims["dispatch_id"]),
            permissions=frozenset(claims.get("permissions") or ()),
            scope=scope,
            jti=str(claims["jti"]),
            credential_version=int(claims.get("credential_version", 0)),
        )

    # --- authorization helpers used by handlers -----------------------------------

    def recheck_grant(self, principal: PackWorkloadPrincipal, permission: str) -> None:
        """Current-grant recheck: DB is the truth even mid-TTL (W5)."""
        if permission not in principal.permissions:
            raise WorkloadVerificationError(
                WorkloadDenyReason.permission_missing,
                f"Разрешения {permission} нет в workload token.",
            )
        effective = PackPermissionService(self.db).effective(
            principal.pack_id, _uuid_or_none(principal.tenant_id)
        )
        if permission not in effective:
            raise WorkloadVerificationError(
                WorkloadDenyReason.grant_revoked,
                f"Грант {permission} отозван после выпуска токена.",
            )

    def authorize_object(
        self,
        principal: PackWorkloadPrincipal,
        resource_type: str,
        resource_id: str,
        *,
        resource_tenant_id: str | None,
    ) -> None:
        """Tenant match then object scope (404 vs 403 policy per D3)."""
        if resource_tenant_id is None or resource_tenant_id != principal.tenant_id:
            self.deny(
                principal,
                WorkloadDenyReason.wrong_tenant,
                permission=None,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Объект не найден.")
        if not principal.scope.allows(resource_type, resource_id):
            self.deny(
                principal,
                WorkloadDenyReason.object_out_of_scope,
                permission=None,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Объект вне scope токена.")

    # --- audit -----------------------------------------------------------------------

    def deny(
        self,
        principal: PackWorkloadPrincipal | None,
        reason: WorkloadDenyReason,
        *,
        permission: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        pack_hint: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        detail: dict[str, Any] = {"reason": reason.value}
        if principal is not None:
            detail.update(
                {
                    "pack_id": principal.pack_id,
                    "tenant_id": principal.tenant_id,
                    "task_id": principal.task_id,
                    "dispatch_id": principal.dispatch_id,
                    "jti": principal.jti,
                }
            )
        elif pack_hint:
            detail["pack_id"] = pack_hint
        if extra:
            for key, value in extra.items():
                detail.setdefault(key, value)
        if permission:
            detail["permission"] = permission
        if resource_type:
            detail["resource_type"] = resource_type
        if resource_id:
            detail["resource_id"] = resource_id
        try:
            AuditService(self.db).record(
                action="pack.workload.denied",
                entity_type="pack_workload",
                entity_id=(principal.pack_id if principal else pack_hint) or "",
                actor_type="system",
                detail=detail,
            )
            self.db.commit()
        except Exception:  # pragma: no cover - auditing must never mask authz
            self.db.rollback()
            logger.warning("failed to persist pack.workload.denied: %s", detail)

    def audited_dispatch(self, claims: dict[str, Any]) -> None:
        AuditService(self.db).record(
            action="pack.workload.dispatched",
            entity_type="pack_workload",
            entity_id=str(claims.get("pack_id", "")),
            actor_type="system",
            detail={
                "dispatch_id": claims.get("dispatch_id"),
                "task_id": claims.get("task_id"),
                "permissions": claims.get("permissions"),
                "scope_mode": (claims.get("scope") or {}).get("mode"),
                "operation": claims.get("operation"),
            },
        )

    # --- internals ----------------------------------------------------------------------

    def _credential_version_of(self, pack_id: str) -> int:
        identity = self.db.scalars(
            select(PackIdentity).where(PackIdentity.pack_id == pack_id)
        ).first()
        return identity.credential_version if identity else 0


def _uuid_or_none(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


__all__ = [
    "OPERATION_PERMISSIONS",
    "WorkloadTokenError",
    "WorkloadTokenService",
    "WorkloadVerificationError",
]
