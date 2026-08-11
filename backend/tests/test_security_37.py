from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from tests.test_analytics import _demo_company_id


@pytest.fixture
def auth_client(db_session):
    """TestClient with the test DB wired but real auth (no get_current_user override)."""
    from fastapi.testclient import TestClient

    from app.core.database import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# --- Security headers / body limit middleware -----------------------------


def test_security_headers_present(auth_client):
    resp = auth_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert "X-Request-ID" in resp.headers


def test_request_body_size_limit_413(auth_client):
    resp = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@agentos.local", "password": "x" * (2 * 1024 * 1024)},
    )
    assert resp.status_code == 413


# --- Production fail-fast --------------------------------------------------


def test_production_validation_blocks_weak_secret():
    from app.core import security
    from app.core.config import settings

    saved = (
        settings.environment,
        settings.jwt_secret,
        settings.database_url,
        settings.debug,
        settings.db_auto_create,
    )
    try:
        settings.environment = "production"
        settings.jwt_secret = "too-short"
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            security.validate_production_settings()

        settings.jwt_secret = "x" * 64
        settings.database_url = "sqlite:///./test.db"
        with pytest.raises(RuntimeError, match="PostgreSQL"):
            security.validate_production_settings()

        settings.database_url = "postgresql://u:p@h/db"
        settings.debug = True
        with pytest.raises(RuntimeError, match="DEBUG"):
            security.validate_production_settings()

        settings.debug = False
        settings.db_auto_create = True
        with pytest.raises(RuntimeError, match="DB_AUTO_CREATE"):
            security.validate_production_settings()

        settings.db_auto_create = False
        security.validate_production_settings()
    finally:
        (
            settings.environment,
            settings.jwt_secret,
            settings.database_url,
            settings.debug,
            settings.db_auto_create,
        ) = saved


# --- JWT hardening ---------------------------------------------------------


def test_jwt_requires_type_claim(auth_client, db_session):
    import jwt as pyjwt
    from datetime import datetime, timedelta, timezone

    from app.core.config import settings
    from app.models import User

    admin = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()

    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(admin.id),
        "iss": settings.jwt_issuer,
        "iat": now,
        "exp": now + timedelta(minutes=10),
        # deliberately NO "type" claim
    }
    forged = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    headers = {"Authorization": f"Bearer {forged}"}
    # Real auth: get_current_user must reject a token without type=access.
    assert auth_client.get("/api/v1/auth/me", headers=headers).status_code == 401

    payload["type"] = "refresh"
    forged = pyjwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    headers = {"Authorization": f"Bearer {forged}"}
    assert auth_client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_me_with_type_access_token_ok(auth_client):
    login = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@agentos.local", "password": "admin123"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert auth_client.get("/api/v1/auth/me", headers=headers).status_code == 200


# --- Rate limiting ---------------------------------------------------------


def test_rate_limiter_local_window(monkeypatch):
    from app.core.rate_limit import RateLimiter
    from app.core.redis import redis_client

    monkeypatch.setattr(redis_client, "_enabled", False)
    limiter = RateLimiter()
    key = f"test:{uuid.uuid4()}"
    assert limiter.hit(key, limit=3, window_seconds=60) is True
    assert limiter.hit(key, limit=3, window_seconds=60) is True
    assert limiter.hit(key, limit=3, window_seconds=60) is True
    assert limiter.hit(key, limit=3, window_seconds=60) is False


def test_login_throttle_lockout_and_reset(monkeypatch):
    from app.core.rate_limit import LoginThrottle, RateLimiter
    from app.core.redis import redis_client

    monkeypatch.setattr(redis_client, "_enabled", False)
    throttle = LoginThrottle(RateLimiter())
    email = f"lock-{uuid.uuid4()}@example.com"

    assert throttle.is_locked(email) is False
    for _ in range(5):
        throttle.record_failure(email)
    assert throttle.is_locked(email) is True

    throttle.record_success(email)
    assert throttle.is_locked(email) is False


def test_login_account_lock_429(auth_client):
    from app.core.rate_limit import LoginThrottle

    email = f"brute-{uuid.uuid4()}@example.com"
    for _ in range(5):
        resp = auth_client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong"}
        )
        assert resp.status_code == 401
    locked = auth_client.post(
        "/api/v1/auth/login", json={"email": email, "password": "wrong"}
    )
    assert locked.status_code == 429
    LoginThrottle().record_success(email)  # cleanup the shared throttle state


# --- Horizontal access (company scoping) -----------------------------------


def _scoped_client(db_session, user):
    """A TestClient whose current user is ``user`` (tenant-scoped manager)."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.core.database import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app)


def _other_company_user(db_session):
    from app.models import Agent, Company, User

    other = Company(name="Конкурент", slug=f"other-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(other)
    db_session.flush()
    manager = User(
        email=f"mgr-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Менеджер конкурента",
        is_active=True,
        is_superuser=False,
        company_id=other.id,
    )
    db_session.add(manager)
    agent = Agent(
        company_id=other.id,
        name="Агент конкурента",
        role="manager",
        slug=f"other-agent-{uuid.uuid4().hex[:8]}",
        goal="",
    )
    db_session.add(agent)
    db_session.commit()
    return other, manager, agent


def test_scoped_manager_sees_only_own_company(db_session):
    from app.main import app
    from app.models import Agent

    other, manager, agent = _other_company_user(db_session)
    mc = _scoped_client(db_session, manager)

    # The manager must not see the demo company's agents (read from DB: the
    # overrides are global, so everything must go through the scoped client).
    demo_agent = db_session.scalars(
        select(Agent).where(Agent.company_id == _demo_company_id(db_session))
    ).first()
    # Scoped list returns only the other company's agent.
    scoped = mc.get("/api/v1/agents").json()
    assert [a["id"] for a in scoped] == [str(agent.id)]

    # Direct access to a demo agent is forbidden.
    resp = mc.get(f"/api/v1/agents/{demo_agent.id}")
    assert resp.status_code == 403

    # Companies list is scoped too.
    companies = mc.get("/api/v1/companies").json()
    assert [c["id"] for c in companies] == [str(other.id)]

    # Cross-company company detail is forbidden.
    demo_company_id = _demo_company_id(db_session)
    assert mc.get(f"/api/v1/companies/{demo_company_id}").status_code == 403

    app.dependency_overrides.clear()


def test_scoped_manager_tasks_and_traces(db_session):
    from app.models import Task
    from app.models.enums import TaskPriority, TaskStatus

    other, manager, agent = _other_company_user(db_session)

    task = Task(
        company_id=_demo_company_id(db_session),
        agent_id=agent.id,
        title="Чужая задача",
        objective="process_customer_message",
        status=TaskStatus.completed,
        priority=TaskPriority.normal,
        input_data={},
    )
    db_session.add(task)
    db_session.commit()

    mc = _scoped_client(db_session, manager)
    assert mc.get(f"/api/v1/tasks/{task.id}").status_code == 403
    scoped_tasks = mc.get("/api/v1/tasks").json()
    assert all(t["company_id"] == str(other.id) for t in scoped_tasks)

    from app.main import app

    app.dependency_overrides.clear()


# --- Audit journal ----------------------------------------------------------


def test_audit_funnel_records_approve_order_create(client, db_session):
    from tests.test_analytics import _drive_to_order

    _drive_to_order(client, db_session)

    data = client.get("/api/v1/audit").json()
    actions = {e["action"] for e in data["items"]}
    assert "approval.approve" in actions
    assert "quote.accept" in actions
    assert "order.create" in actions
    assert data["total"] == len(data["items"])

    approve = next(e for e in data["items"] if e["action"] == "approval.approve")
    assert approve["actor_type"] == "user"
    assert approve["entity_type"] == "approval"

    order_event = next(e for e in data["items"] if e["action"] == "order.create")
    assert order_event["detail"]["order_number"]


def test_audit_replay_and_user_create(client, db_session):
    from app.models import Task
    from app.models.enums import TaskPriority, TaskStatus
    from app.services.user_service import UserService
    from tests.test_analytics import _demo_company_id

    task = Task(
        company_id=_demo_company_id(db_session),
        title="replay-me",
        objective="process_customer_message",
        status=TaskStatus.completed,
        priority=TaskPriority.normal,
        input_data={},
    )
    db_session.add(task)
    db_session.commit()

    replayed = client.post(f"/api/v1/tasks/{task.id}/replay").json()
    assert replayed["id"]

    UserService(db_session).create(
        email=f"new-{uuid.uuid4().hex[:8]}@example.com",
        password="strong-pass-123",
        full_name="Новый менеджер",
        company_id=_demo_company_id(db_session),
    )
    db_session.commit()

    data = client.get("/api/v1/audit").json()
    actions = {e["action"] for e in data["items"]}
    assert "task.replay" in actions
    assert "user.create" in actions

    replay = next(e for e in data["items"] if e["action"] == "task.replay")
    assert replay["entity_id"] == replayed["id"]
    assert replay["detail"]["replayed_from_task_id"] == str(task.id)


def test_audit_scoped_to_company(db_session):
    from app.models import AuditEvent

    other, manager, _ = _other_company_user(db_session)

    event = AuditEvent(
        action="order.create",
        entity_type="order",
        entity_id=str(uuid.uuid4()),
        company_id=other.id,
        user_id=manager.id,
        detail={"order_number": "X-1"},
    )
    db_session.add(event)
    db_session.commit()

    mc = _scoped_client(db_session, manager)
    mine = mc.get("/api/v1/audit").json()
    assert {e["id"] for e in mine["items"]} == {str(event.id)}

    # Demo company's audit records are invisible to the manager.
    demo = AuditEvent(
        action="approval.approve",
        entity_type="approval",
        entity_id=str(uuid.uuid4()),
        company_id=_demo_company_id(db_session),
        detail={},
    )
    db_session.add(demo)
    db_session.commit()
    assert mc.get(f"/api/v1/audit/{demo.id}").status_code == 403

    from app.api.deps import get_current_user
    from app.main import app

    app.dependency_overrides.clear()
