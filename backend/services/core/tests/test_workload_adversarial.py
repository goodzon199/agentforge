"""Sprint 5.9.3 adversarial suite (contract 5A.11, invariants I1–I4).

Every test maps to a W-row of the workload delegation matrix or to an
approved invariant. Tokens are minted through the real
``WorkloadTokenService`` and pushed through the real Context API.
"""

from __future__ import annotations

import datetime as dt
import uuid

import jwt as pyjwt
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.workload import (
    OPERATION_PERMISSIONS,
    WorkloadScope,
    WorkloadTokenError,
    operation_key,
    required_permissions_for,
)
from app.models import (
    AuditEvent,
    Company,
    Conversation,
    ConversationMessage,
    Customer,
    Pack,
)
from app.services.pack_identity_service import PackIdentityService
from app.services.pack_permission_service import PackPermissionService
from app.services.workload_token_service import (
    WorkloadTokenService,
    WorkloadVerificationError,
)

# --- fixtures ------------------------------------------------------------------


@pytest.fixture
def two_companies(db_session):
    a = Company(name="WCoA", slug=f"wco-a-{uuid.uuid4().hex[:6]}")
    b = Company(name="WCoB", slug=f"wco-b-{uuid.uuid4().hex[:6]}")
    db_session.add_all([a, b])
    db_session.flush()
    return a, b


@pytest.fixture
def pack_env(db_session, two_companies, monkeypatch):
    """Registered pack with identity, grants and one conversation per tenant."""
    monkeypatch.setitem(
        OPERATION_PERMISSIONS,
        "dispatch.wpack.intake",
        frozenset({"customer.read", "conversation.read"}),
    )
    company_a, company_b = two_companies

    def conv_for(company):
        customer = Customer(company_id=company.id, name=f"C-{company.slug}")
        db_session.add(customer)
        db_session.flush()
        conversation = Conversation(
            company_id=company.id, customer_id=customer.id
        )
        db_session.add(conversation)
        db_session.flush()
        message = ConversationMessage(
            conversation_id=conversation.id,
            content="msg",
            sender_type="customer",
        )
        db_session.add(message)
        return conversation, customer, message

    conv_a, cust_a, msg_a = conv_for(company_a)
    conv_b, cust_b, msg_b = conv_for(company_b)

    db_session.add(
        Pack(
            name="wpack",
            version="1.0.0",
            base_url="http://localhost:9",
            permissions=["conversation.read", "customer.read"],
            state="active",
            is_active=True,
            agents=[{"type": "intake"}],
        )
    )
    db_session.flush()
    identity = PackIdentityService(db_session).ensure("wpack")
    assert identity.credential_version == 1
    perms = PackPermissionService(db_session)
    perms.sync_declared(
        "wpack", ["conversation.read", "customer.read"], "1.0.0"
    )
    for perm in ("conversation.read", "customer.read"):
        perms.grant("wpack", perm, actor_id=None, tenant_id=company_a.id)
        perms.grant("wpack", perm, actor_id=None, tenant_id=company_b.id)
    db_session.commit()
    return {
        "companies": (company_a, company_b),
        "a": (conv_a, cust_a, msg_a),
        "b": (conv_b, cust_b, msg_b),
    }


def _issue(db, env, *, tenant="a", operation=None, scope=None, scope_mode="explicit",
           deadline=None, task_id=None, dispatch_id=None):
    company = env["companies"][0 if tenant == "a" else 1]
    conversation, customer, message = env[tenant]
    svc = WorkloadTokenService(db)
    explicit = (
        WorkloadScope(
            conversation_ids=frozenset({str(conversation.id)}),
            customer_ids=frozenset({str(customer.id)}),
            message_ids=frozenset({str(message.id)}),
        )
        if scope_mode != "tenant"
        else None
    )
    token, claims = svc.issue(
        pack_id="wpack",
        tenant_id=str(company.id),
        task_id=task_id or str(uuid.uuid4()),
        dispatch_id=dispatch_id or str(uuid.uuid4()),
        operation=operation or "dispatch.wpack.intake",
        scope=scope or explicit,
        scope_mode=scope_mode,
        task_deadline=deadline,
    )
    svc.record_dispatch(
        dispatch_id=claims["dispatch_id"],
        pack_id="wpack",
        operation=claims["operation"],
        jti=claims["jti"],
        task_id=claims["task_id"],
        company_id=str(company.id),
    )
    db.commit()
    return token, claims


def _get(client, path, token):
    return client.get(
        path,
        headers={
            "X-Internal-Token": settings.internal_api_token,
            "Authorization": f"Bearer {token}",
        },
    )


# --- W1: /internal/token never issues workload tokens ---------------------------


def test_w1_token_endpoint_is_service_only(db_session, client):
    from app.core.workload import TOKEN_TYPE_SERVICE

    identity = PackIdentityService(db_session).ensure("wpack")
    token, _ = PackIdentityService(db_session).issue_service_token(identity)
    db_session.commit()
    claims = pyjwt.decode(token, options={"verify_signature": False})
    assert claims["token_type"] == TOKEN_TYPE_SERVICE
    assert "tenant_id" not in claims and "permissions" not in claims


# --- W2/W3: tenant and object isolation -------------------------------------------


def test_w2_cross_tenant_customer_is_404(db_session, client, pack_env):
    token, _ = _issue(db_session, pack_env, tenant="a")
    _, cust_b, _ = pack_env["b"]
    response = _get(
        client, f"/internal/context/customers/{cust_b.id}", token
    )
    assert response.status_code == 404  # existence hidden across tenants


def test_w3_same_tenant_out_of_scope_conversation_is_403(db_session, client, pack_env):
    company_a = pack_env["companies"][0]
    extra = Conversation(company_id=company_a.id, customer_id=pack_env["a"][1].id)
    db_session.add(extra)
    db_session.flush()
    token, _ = _issue(db_session, pack_env, tenant="a")  # scoped to conv A only
    response = _get(
        client, f"/internal/context/conversations/{extra.id}", token
    )
    assert response.status_code == 403


# --- W4: missing permission claim ---------------------------------------------------


def test_w4_operation_without_customer_read_is_denied(
    db_session, client, pack_env, monkeypatch
):
    # An operation whose requirement set lacks customer.read.
    monkeypatch.setitem(
        OPERATION_PERMISSIONS,
        "dispatch.wpack.intake",
        frozenset({"supplier.search"}),
    )
    token, claims = _issue(db_session, pack_env)
    assert "customer.read" not in claims["permissions"]
    _, customer, _, = pack_env["a"]
    response = _get(
        client, f"/internal/context/customers/{customer.id}", token
    )
    assert response.status_code == 403


# --- W5: grant revoked after issuance ------------------------------------------------


def test_w5_revoked_grant_denies_immediately(db_session, client, pack_env):
    token, _ = _issue(db_session, pack_env, tenant="a")
    company_a = pack_env["companies"][0]
    PackPermissionService(db_session).revoke(
        "wpack", "customer.read", actor_id=None, tenant_id=company_a.id
    )
    db_session.commit()

    _, customer, _ = pack_env["a"]
    response = _get(
        client, f"/internal/context/customers/{customer.id}", token
    )
    assert response.status_code == 403
    events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "pack.workload.denied")
    ).all()
    assert any(e.detail.get("reason") == "grant_revoked" for e in events)


# --- W6: credential_version mismatch --------------------------------------------------


def test_w6_rotation_invalidates_outstanding_tokens(db_session, client, pack_env):
    token, _ = _issue(db_session, pack_env, tenant="a")
    # First provision seeds the hash; the second one is a real rotation.
    PackIdentityService(db_session).provision("wpack")
    PackIdentityService(db_session).provision("wpack")  # cv 1 → 2
    db_session.commit()

    conversation, _, _ = pack_env["a"]
    response = _get(
        client, f"/internal/context/conversations/{conversation.id}", token
    )
    assert response.status_code == 401


# --- W7: disabled identity ------------------------------------------------------------


def test_w7_disabled_pack_is_denied(db_session, client, pack_env):
    from app.models import PackIdentityStatus

    token, _ = _issue(db_session, pack_env, tenant="a")
    PackIdentityService(db_session).set_status(
        "wpack", PackIdentityStatus.disabled
    )
    db_session.commit()

    conversation, _, _ = pack_env["a"]
    response = _get(
        client, f"/internal/context/conversations/{conversation.id}", token
    )
    assert response.status_code == 401


# --- W8: expired JWT --------------------------------------------------------------------


def test_w8_expired_token_is_401(db_session, client, pack_env):
    company_a = pack_env["companies"][0]
    conversation, _, message = pack_env["a"]
    now = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    payload = {
        "iss": "agentos-core",
        "aud": "agentos-internal",
        "token_type": "workload",
        "pack_id": "wpack",
        "tenant_id": str(company_a.id),
        "task_id": str(uuid.uuid4()),
        "dispatch_id": str(uuid.uuid4()),
        "permissions": ["conversation.read"],
        "scope": {"mode": "explicit"},
        "jti": uuid.uuid4().hex,
        "credential_version": 1,
        "iat": now,
        "nbf": now,
        "exp": now + dt.timedelta(minutes=5),  # long past, leeway is 10s
    }
    token = pyjwt.encode(payload, settings.internal_jwt_key, algorithm="HS256")

    response = _get(
        client, f"/internal/context/conversations/{conversation.id}", token
    )
    assert response.status_code == 401


# --- W9: tampered scope → signature failure -----------------------------------------------


def test_w9_tampered_scope_fails_signature(db_session, client, pack_env):
    token, claims = _issue(db_session, pack_env, tenant="a")
    header = pyjwt.get_unverified_header(token)
    forged = pyjwt.encode(
        {**claims, "scope": {"mode": "tenant"}},
        "attacker-key-not-core-secret",
        algorithm="HS256",
        headers=header,
    )
    conversation, _, _ = pack_env["a"]
    response = _get(
        client, f"/internal/context/conversations/{conversation.id}", forged
    )
    assert response.status_code == 401


# --- W10: replay / superseded dispatch ------------------------------------------------------


def test_w10_replayed_dispatch_kills_old_token(db_session, client, pack_env):
    old_task = str(uuid.uuid4())
    old_token, old_claims = _issue(
        db_session, pack_env, tenant="a", task_id=old_task
    )

    svc = WorkloadTokenService(db_session)
    svc.supersede_task_dispatches(old_task)  # new dispatch for same task
    new_token, _ = _issue(
        db_session, pack_env, tenant="a", task_id=old_task
    )
    db_session.commit()

    conversation, _, _ = pack_env["a"]
    assert (
        _get(client, f"/internal/context/conversations/{conversation.id}", old_token).status_code
        == 401
    )
    # The fresh capability keeps working.
    assert (
        _get(client, f"/internal/context/conversations/{conversation.id}", new_token).status_code
        == 200
    )


def test_completed_task_invalidates_tokens(db_session, client, pack_env):
    token, claims = _issue(db_session, pack_env, tenant="a")
    WorkloadTokenService(db_session).mark_task_dispatches_terminal(
        claims["task_id"], failed=False
    )
    db_session.commit()
    conversation, _, _ = pack_env["a"]
    assert (
        _get(client, f"/internal/context/conversations/{conversation.id}", token).status_code
        == 401
    )


# --- W11: valid token + own scoped object -----------------------------------------------------


def test_w11_valid_scoped_flow_allowed(db_session, client, pack_env):
    token, _ = _issue(db_session, pack_env, tenant="a")
    conversation, customer, _ = pack_env["a"]
    ok_conv = _get(
        client, f"/internal/context/conversations/{conversation.id}", token
    )
    ok_cust = _get(
        client, f"/internal/context/customers/{customer.id}", token
    )
    assert ok_conv.status_code == 200 and ok_cust.status_code == 200
    body = ok_conv.json()
    assert body["customer"]["id"] == str(customer.id)  # customer.read in scope


# --- Invariant I2: fail-closed operation registry ----------------------------------------------


def test_i2_unknown_operation_refused():
    with pytest.raises(WorkloadTokenError):
        required_permissions_for("dispatch.unknownpack.greeting")


def test_i2_registry_covers_builtin_manifest_agents():
    expected = {
        operation_key("autoparts", t)
        for t in ("intake", "search", "pricing", "sales", "order")
    } | {
        operation_key("beauty", t)
        for t in ("reception", "calendar", "booking", "sales", "reminder")
    }
    assert expected <= set(OPERATION_PERMISSIONS)


def test_i2_issue_with_unknown_operation_raises(db_session, pack_env):
    svc = WorkloadTokenService(db_session)
    with pytest.raises(WorkloadTokenError):
        svc.issue(
            pack_id="wpack",
            tenant_id=str(pack_env["companies"][0].id),
            task_id=str(uuid.uuid4()),
            dispatch_id=str(uuid.uuid4()),
            operation="dispatch.wpack.nosuchagent",
        )


# --- Invariant I3: tenant-scope allowlist --------------------------------------------------------


def test_i3_tenant_scope_requires_allowlist(db_session, pack_env):
    svc = WorkloadTokenService(db_session)
    with pytest.raises(WorkloadTokenError):
        svc.issue(
            pack_id="wpack",
            tenant_id=str(pack_env["companies"][0].id),
            task_id=str(uuid.uuid4()),
            dispatch_id=str(uuid.uuid4()),
            operation="dispatch.wpack.intake",
            scope_mode="tenant",  # intake is NOT allowlisted
        )


def test_i3_allowlisted_operation_accepts_tenant_scope(db_session, pack_env, monkeypatch):
    monkeypatch.setattr(
        "app.core.workload.TENANT_SCOPE_OPERATIONS",
        frozenset({"dispatch.wpack.intake"}),
    )
    token, claims = _issue(
        db_session, pack_env, tenant="a", scope_mode="tenant"
    )
    assert claims["scope"]["mode"] == "tenant"
    # Tenant-wide scope reads any object of the tenant.
    company_a = pack_env["companies"][0]
    extra = Conversation(company_id=company_a.id, customer_id=pack_env["a"][1].id)
    db_session.add(extra)
    db_session.flush()

    from fastapi.testclient import TestClient

    from app.core.database import get_db
    from app.main import app

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        resp = TestClient(app).get(
            f"/internal/context/conversations/{extra.id}",
            headers={
                "X-Internal-Token": settings.internal_api_token,
                "Authorization": f"Bearer {token}",
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert resp.status_code == 200


def test_verify_rejects_unallowlisted_tenant_claim(db_session, pack_env):
    """A hand-forged tenant-scope token fails verification even if signed."""
    company_a = pack_env["companies"][0]
    svc = WorkloadTokenService(db_session)
    raw_claims = {
        "iss": "agentos-core",
        "aud": "agentos-internal",
        "token_type": "workload",
        "pack_id": "wpack",
        "tenant_id": str(company_a.id),
        "task_id": str(uuid.uuid4()),
        "dispatch_id": str(uuid.uuid4()),
        "permissions": ["conversation.read"],
        "scope": {"mode": "tenant"},  # not allowlisted for this op
        "operation": "dispatch.wpack.intake",
        "jti": uuid.uuid4().hex,
        "credential_version": 1,
    }
    token = pyjwt.encode(raw_claims, settings.internal_jwt_key, algorithm="HS256")
    with pytest.raises(WorkloadVerificationError):
        svc.verify(token)


# --- Invariant I4: TTL rules -----------------------------------------------------------------------


def test_i4_expired_task_deadline_blocks_issuance(db_session, pack_env):
    svc = WorkloadTokenService(db_session)
    past = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=30)
    with pytest.raises(WorkloadTokenError):
        svc.issue(
            pack_id="wpack",
            tenant_id=str(pack_env["companies"][0].id),
            task_id=str(uuid.uuid4()),
            dispatch_id=str(uuid.uuid4()),
            operation="dispatch.wpack.intake",
            task_deadline=past,
        )


def test_i4_exp_capped_by_task_deadline(db_session, pack_env):
    deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=42)
    _, claims = _issue(db_session, pack_env, tenant="a", deadline=deadline)
    assert claims["exp"] <= deadline
