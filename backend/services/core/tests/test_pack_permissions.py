"""Sprint 5.9.2 DoD: declared vs granted permissions, tenant scoping, RBAC."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.pack_permissions import CATALOG, risk_of
from app.models import PackPermissionGrant, User
from app.services.pack_permission_service import (
    PackPermissionError,
    PackPermissionService,
)
from app.services.pack_service import PackError, PackService


def _manifest(name="evilpack", version="1.0.0", permissions=None):
    return {
        "name": name,
        "version": version,
        "display_name": name.title(),
        "agents": [{"type": "intake"}],
        "permissions": list(permissions if permissions is not None else []),
        "workflows": [],
        "tools": [],
        "required_core_version": ">=0.5.0",
        "developer": "DoD Tester",
        "license": "MIT",
    }


def _register(db_session, **kwargs):
    return PackService(db_session).register_manifest("http://pack:8000", _manifest(**kwargs))


def _perm_svc(db_session):
    return PackPermissionService(db_session)


@pytest.fixture
def registered_autoparts(db_session):
    """Register builtin packs and run the one-time bootstrap transfer."""
    PackService(db_session).register_manifest(
        "http://autoparts:8000",
        _manifest(name="autoparts", permissions=[
            "customer.read", "conversation.write", "supplier.search",
            "quote.create", "order.create",
        ]),
    )
    PackService(db_session).register_manifest(
        "http://beauty:8000",
        _manifest(name="beauty", permissions=[
            "customer.read", "calendar.read", "calendar.write",
            "booking.create", "notification.send",
        ]),
    )
    counts = _perm_svc(db_session).bootstrap_builtin()
    db_session.commit()
    assert counts == {"autoparts": 5, "beauty": 5}
    return counts


# --- catalog ------------------------------------------------------------------


def test_catalog_covers_builtin_manifest_permissions():
    for perm in ("supplier.order", "order.create"):
        assert CATALOG[perm].risk_level.value == "HIGH"
    assert risk_of("supplier.search").value == "MEDIUM"


# --- bootstrap (DoD 1) ----------------------------------------------------------


def test_bootstrap_grants_are_migration_sourced(db_session, registered_autoparts):
    svc = _perm_svc(db_session)
    eff = svc.effective("autoparts")
    assert {"customer.read", "conversation.write", "supplier.search",
            "quote.create", "order.create"} <= eff
    rows = db_session.scalars(
        select(PackPermissionGrant).where(PackPermissionGrant.pack_id == "autoparts")
    ).all()
    assert all(r.grant_source == "migration_bootstrap" for r in rows)


def test_bootstrap_is_idempotent(db_session, registered_autoparts):
    counts = _perm_svc(db_session).bootstrap_builtin()
    assert counts == {}


# --- new pack starts with nothing (DoD 2) ----------------------------------------


def test_new_pack_declared_without_grants(db_session):
    _register(db_session, name="freshpack", permissions=["customer.read"])
    db_session.commit()
    snap = _perm_svc(db_session).snapshot("freshpack")
    assert snap["declared"] == ["customer.read"]
    assert snap["granted"] == []
    assert snap["effective"] == []
    assert snap["pending"] == ["customer.read"]


# --- grant / revoke lifecycle (DoD 3, 4) -----------------------------------------


def test_grant_then_revoke_roundtrip(db_session):
    _register(db_session, name="freshpack", permissions=["customer.read"])
    db_session.commit()
    svc = _perm_svc(db_session)

    svc.grant("freshpack", "customer.read", actor_id=None, reason="dod")
    db_session.commit()
    assert svc.effective("freshpack") == {"customer.read"}
    assert svc.pending("freshpack") == set()

    svc.revoke("freshpack", "customer.read", actor_id=None, reason="dod-revoke")
    db_session.commit()
    assert svc.effective("freshpack") == set()
    assert svc.pending("freshpack") == {"customer.read"}


# --- intersection invariant (DoD 5, 6) --------------------------------------------


def test_granted_but_not_declared_is_denied(db_session):
    _register(db_session, name="freshpack", permissions=["customer.read"])
    svc = _perm_svc(db_session)
    svc.grant("freshpack", "customer.read", actor_id=None)
    # A stale active row for a permission that was never declared.
    db_session.add(PackPermissionGrant(
        pack_id="freshpack", permission="order.create", status="active",
    ))
    db_session.commit()
    # Only the declared∩granted permission counts; the stale one is ignored.
    assert svc.effective("freshpack") == {"customer.read"}


def test_cannot_grant_undeclared_permission(db_session):
    _register(db_session, name="freshpack", permissions=[])
    db_session.commit()
    with pytest.raises(PackPermissionError):
        _perm_svc(db_session).grant("freshpack", "order.create", actor_id=None)


# --- unknown permission in manifest (DoD 7) ---------------------------------------


def test_unknown_permission_in_manifest_is_validation_error(db_session):
    with pytest.raises(PackError) as excinfo:
        _register(db_session, name="badpack",
                  permissions=["customer.read", "bank.account.read"])
    assert "bank.account.read" in str(excinfo.value)


# --- upgrade flow (DoD 8) -----------------------------------------------------------


def test_upgrade_adding_permission_requires_review(db_session):
    _register(db_session, name="vendorpack", version="1.0.0",
              permissions=["customer.read"])
    svc = _perm_svc(db_session)
    svc.grant("vendorpack", "customer.read", actor_id=None)
    db_session.commit()

    _register(db_session, name="vendorpack", version="1.1.0",
              permissions=["customer.read", "supplier.order"])
    db_session.commit()

    snap = svc.snapshot("vendorpack")
    assert snap["declared"] == ["customer.read", "supplier.order"]
    # Existing rights keep working; the new HIGH permission stays pending.
    assert snap["effective"] == ["customer.read"]
    assert snap["pending"] == ["supplier.order"]
    rows = db_session.scalars(
        select(PackPermissionGrant).where(
            PackPermissionGrant.pack_id == "vendorpack",
            PackPermissionGrant.permission == "supplier.order",
        )
    ).all()
    assert rows == []  # no auto-grant ever happened


# --- removal / return of permissions (DoD 9) -----------------------------------------


def test_removed_permission_deactivates_grant_but_keeps_row(db_session):
    _register(db_session, name="vendorpack", permissions=["customer.read"])
    svc = _perm_svc(db_session)
    svc.grant("vendorpack", "customer.read", actor_id=None)
    db_session.commit()

    _register(db_session, name="vendorpack", version="2.0.0", permissions=[])
    db_session.commit()
    assert svc.effective("vendorpack") == set()

    row = db_session.scalars(
        select(PackPermissionGrant).where(PackPermissionGrant.pack_id == "vendorpack")
    ).one()
    assert row.status == "inactive_not_declared"

    # Permission returns in a newer version.
    _register(db_session, name="vendorpack", version="2.1.0",
              permissions=["customer.read"])
    db_session.commit()
    if risk_of("customer.read").value != "HIGH":
        # LOW/MEDIUM grants are restored automatically.
        assert svc.effective("vendorpack") == {"customer.read"}


def test_high_risk_return_requires_explicit_re_review(db_session):
    _register(db_session, name="vendorpack", permissions=["order.create"])
    svc = _perm_svc(db_session)
    svc.grant("vendorpack", "order.create", actor_id=None)
    db_session.commit()

    _register(db_session, name="vendorpack", version="2.0.0", permissions=[])
    db_session.commit()
    _register(db_session, name="vendorpack", version="2.1.0",
              permissions=["order.create"])
    db_session.commit()

    assert svc.pending("vendorpack") == {"order.create"}
    assert svc.effective("vendorpack") == set()

    # The explicit admin re-grant is the review decision.
    svc.grant("vendorpack", "order.create", actor_id=None, reason="re_review")
    db_session.commit()
    assert svc.effective("vendorpack") == {"order.create"}


# --- tenant scoping (DoD 10) -----------------------------------------------------------


def test_tenant_scoped_grant_does_not_leak_across_tenants(db_session):
    company_a, company_b = uuid.uuid4(), uuid.uuid4()
    _register(db_session, name="vendorpack", permissions=["order.create"])
    svc = _perm_svc(db_session)

    svc.grant("vendorpack", "order.create", actor_id=None, tenant_id=company_a)
    db_session.commit()

    assert svc.effective("vendorpack", tenant_id=company_a) == {"order.create"}
    assert svc.effective("vendorpack", tenant_id=company_b) == set()
    # Global view ignores tenant-specific grants entirely.
    assert svc.effective("vendorpack") == set()


# --- API + RBAC (DoD 11, 12) ------------------------------------------------------------


@pytest.fixture
def as_role(db_session):
    """TestClient acting as a user with the given role; overrides cleaned up."""
    from app.api.deps import get_current_user
    from app.core.database import get_db
    from app.main import app

    made: dict[str, TestClient] = {}

    def _make(role: str, *, superuser: bool = False) -> TestClient:
        actor = User(email=f"{role}-{uuid.uuid4().hex[:6]}@t.local", role=role,
                     is_superuser=superuser, full_name=role, hashed_password="x")

        def override_user():
            return actor

        def override_db():
            yield db_session

        app.dependency_overrides[get_current_user] = override_user
        app.dependency_overrides[get_db] = override_db
        c = TestClient(app)
        made[role] = c
        return c

    yield _make
    app.dependency_overrides.clear()


def test_owner_can_grant_manager_cannot(db_session, as_role):
    _register(db_session, name="rbacpack", permissions=["customer.read"])
    db_session.commit()

    owner = as_role("owner")
    resp = owner.post("/api/v1/packs/rbacpack/permissions/customer.read/grant",
                      json={"reason": "dod"})
    assert resp.status_code == 200

    manager = as_role("manager")
    assert manager.post(
        "/api/v1/packs/rbacpack/permissions/customer.read/revoke", json={}
    ).status_code == 403
    assert manager.post(
        "/api/v1/packs/rbacpack/permissions/conversation.write/grant", json={}
    ).status_code == 403
    # Owner's grant survived the manager's attempts.
    assert db_session.scalars(
        select(PackPermissionGrant).where(PackPermissionGrant.pack_id == "rbacpack")
    ).one().status == "active"


def test_get_permissions_endpoint_shape(db_session, client):
    _register(db_session, name="shapepack",
              permissions=["customer.read", "order.create"])
    db_session.commit()
    resp = client.get("/api/v1/packs/shapepack/permissions")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"pack", "declared", "granted", "effective", "pending"}
    assert body["declared"] == ["customer.read", "order.create"]
    assert body["granted"] == []
    assert body["pending"] == ["customer.read", "order.create"]


def test_unknown_permission_grant_is_422(db_session, client):
    _register(db_session, name="shapepack", permissions=[])
    db_session.commit()
    resp = client.post("/api/v1/packs/shapepack/permissions/no.such/grant", json={})
    assert resp.status_code == 422


# --- audit (DoD 13) -----------------------------------------------------------------------


def test_permission_changes_are_audited(db_session):
    from app.models import AuditEvent

    _register(db_session, name="auditpack", permissions=["customer.read"])
    svc = _perm_svc(db_session)
    svc.grant("auditpack", "customer.read", actor_id=None, reason="dod")
    svc.revoke("auditpack", "customer.read", actor_id=None, reason="dod-off")
    db_session.commit()

    actions = [
        row.action
        for row in db_session.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "pack_permissions")
        ).all()
    ]
    assert "pack.permission.requested" in actions
    assert "pack.permission.granted" in actions
    assert "pack.permission.revoked" in actions


# --- EvilPack adversarial (early 5.9 proof) -------------------------------------------------


def test_evilpack_manifest_edit_yields_no_powers(db_session, client):
    """EvilPack declares order.create at register time — and gets nothing."""
    _register(db_session, name="evilpack",
              permissions=["order.create", "memory.read"])
    db_session.commit()

    resp = client.get("/api/v1/packs/evilpack/permissions")
    body = resp.json()
    assert body["declared"] == ["memory.read", "order.create"]
    assert body["effective"] == []  # nothing usable
    assert sorted(body["pending"]) == ["memory.read", "order.create"]
