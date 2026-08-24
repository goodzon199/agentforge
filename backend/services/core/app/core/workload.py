"""Workload delegation domain (sprint 5.9.3, contract section 5A).

Central definitions for the three token types Core signs (invariant I1),
the fail-closed operation registry (I2) and the tenant-scope allowlist (I3).
Packs never import this module — they only receive ready bearer tokens.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

# --- Invariant I1: explicit token types --------------------------------------

TOKEN_TYPE_SERVICE = "service"
TOKEN_TYPE_WORKLOAD = "workload"
TOKEN_TYPE_DISPATCH = "dispatch"


class WorkloadDenyReason(str, enum.Enum):
    """Audit reasons for pack.workload.denied (contract 5A.5)."""

    token_invalid = "token_invalid"  # signature/format/exp/nbf/token_type
    identity_disabled = "identity_disabled"
    identity_missing = "identity_missing"
    credential_version_mismatch = "credential_version_mismatch"
    token_revoked = "token_revoked"  # jti denylist or dispatch not active
    permission_missing = "permission_missing"
    grant_revoked = "grant_revoked"  # DB recheck after issuance
    wrong_tenant = "wrong_tenant"
    object_out_of_scope = "object_out_of_scope"


class WorkloadTokenError(Exception):
    """Core-side refusal to ISSUE a workload token (fail-closed paths)."""


# --- Invariant I2: operation registry (fail-closed) ---------------------------
#
# Key format: ``dispatch.<pack>.<agent_type>`` — one entry per dispatched
# operation. A dispatch whose operation is missing here is REFUSED, never
# continued with empty permissions.

OPERATION_PERMISSIONS: dict[str, frozenset[str]] = {
    # autoparts
    "dispatch.autoparts.intake": frozenset({"customer.read", "conversation.read"}),
    "dispatch.autoparts.search": frozenset({"supplier.search"}),
    "dispatch.autoparts.pricing": frozenset({"quote.read"}),
    "dispatch.autoparts.sales": frozenset({"quote.read", "quote.create"}),
    "dispatch.autoparts.order": frozenset({"order.read", "order.create"}),
    # beauty
    "dispatch.beauty.reception": frozenset({"customer.read"}),
    "dispatch.beauty.calendar": frozenset({"calendar.read"}),
    "dispatch.beauty.booking": frozenset({"calendar.write", "booking.create"}),
    "dispatch.beauty.reminder": frozenset({"notification.send"}),
}

# beauty has its own sales agent; permissions may differ per pack later.
OPERATION_PERMISSIONS["dispatch.beauty.sales"] = frozenset({"customer.read"})


def required_permissions_for(operation: str) -> frozenset[str]:
    """Fail-closed lookup (I2): unknown operation raises."""
    try:
        return OPERATION_PERMISSIONS[operation]
    except KeyError:
        raise WorkloadTokenError(
            f"Операция {operation!r} отсутствует в OPERATION_PERMISSIONS — "
            "dispatch запрещён (fail-closed)."
        ) from None


def operation_key(pack_name: str | None, agent_type: str) -> str:
    return f"dispatch.{pack_name or 'unknown'}.{agent_type}"


# --- Invariant I3: tenant-scope allowlist --------------------------------------
#
# scope_mode=tenant is an exception requiring an explicit registry entry;
# everything defaults to explicit object scope.

TENANT_SCOPE_OPERATIONS: frozenset[str] = frozenset()


def tenant_scope_allowed(operation: str) -> bool:
    return operation in TENANT_SCOPE_OPERATIONS


# --- Scope and principal -------------------------------------------------------

SCOPE_MODE_EXPLICIT = "explicit"
SCOPE_MODE_TENANT = "tenant"

_SCOPE_RESOURCE_FIELDS = ("conversation_ids", "customer_ids", "message_ids")


@dataclass(frozen=True)
class WorkloadScope:
    mode: str = SCOPE_MODE_EXPLICIT
    conversation_ids: frozenset[str] = field(default_factory=frozenset)
    customer_ids: frozenset[str] = field(default_factory=frozenset)
    message_ids: frozenset[str] = field(default_factory=frozenset)

    def to_claims(self) -> dict:
        if self.mode == SCOPE_MODE_TENANT:
            return {"mode": SCOPE_MODE_TENANT}
        return {
            "mode": SCOPE_MODE_EXPLICIT,
            "conversation_ids": sorted(self.conversation_ids),
            "customer_ids": sorted(self.customer_ids),
            "message_ids": sorted(self.message_ids),
        }

    @classmethod
    def from_claims(cls, claims: dict) -> WorkloadScope:
        raw = claims.get("scope") or {}
        mode = raw.get("mode", SCOPE_MODE_EXPLICIT)
        if mode == SCOPE_MODE_TENANT:
            return cls(mode=SCOPE_MODE_TENANT)
        return cls(
            mode=SCOPE_MODE_EXPLICIT,
            **{
                name: frozenset(raw.get(name) or ())
                for name in _SCOPE_RESOURCE_FIELDS
            },
        )

    def allows(self, resource_type: str, resource_id: str) -> bool:
        """D4: explicit mode + absent/empty resource type = denied."""
        if self.mode == SCOPE_MODE_TENANT:
            return True
        allowed = getattr(self, f"{resource_type}_ids", None)
        if allowed is None:  # unknown resource type never passes
            return False
        return resource_id in allowed


@dataclass(frozen=True)
class PackWorkloadPrincipal:
    """Verified workload identity handed to internal handlers."""

    pack_id: str
    tenant_id: str
    task_id: str
    dispatch_id: str
    permissions: frozenset[str]
    scope: WorkloadScope
    jti: str
    credential_version: int
