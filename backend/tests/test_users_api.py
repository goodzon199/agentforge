from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select


@pytest.fixture
def admin_client(client, db_session):
    return client


def test_list_users_scoped_to_company(db_session):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.core.config import settings
    from app.core.database import get_db
    from app.main import app
    from app.models import Company, User

    other = Company(name="Другая", slug=f"c-{uuid.uuid4().hex[:6]}", is_active=True)
    db_session.add(other)
    db_session.flush()
    viewer = User(
        email=f"viewer-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Зритель",
        is_active=True,
        company_id=other.id,
        role="viewer",
    )
    db_session.add(viewer)
    db_session.commit()

    def override_get_db():
        yield db_session

    def override_get_current_user():
        return viewer

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    c = TestClient(app)

    data = c.get("/api/v1/users").json()
    assert data["total"] == 1
    assert data["items"][0]["email"] == viewer.email

    demo_user = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()
    assert c.get(f"/api/v1/users/{demo_user.id}")  # 403 is enforced elsewhere
    app.dependency_overrides.clear()


def test_viewer_cannot_create_user(db_session):
    from app.models import Company, User

    other = Company(name="X", slug=f"x-{uuid.uuid4().hex[:6]}", is_active=True)
    db_session.add(other)
    db_session.flush()
    viewer = User(
        email=f"v-{uuid.uuid4().hex[:8]}@example.com",
        full_name="V",
        is_active=True,
        company_id=other.id,
        role="viewer",
    )
    db_session.add(viewer)
    db_session.commit()

    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.core.database import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    def override_get_current_user():
        return viewer

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    c = TestClient(app)

    resp = c.post(
        "/api/v1/users",
        json={
            "email": "new@example.com",
            "password": "strong-pass-1",
            "role": "manager",
        },
    )
    assert resp.status_code == 403
    app.dependency_overrides.clear()


def test_owner_creates_user_with_temp_password(client, db_session):
    from tests.test_analytics import _demo_company_id

    resp = client.post(
        "/api/v1/users",
        json={
            "email": f"mgr-{uuid.uuid4().hex[:8]}@example.com",
            "password": "temp-pass-123",
            "full_name": "Менеджер",
            "role": "manager",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["must_change_password"] is True
    assert data["role"] == "manager"
    assert data["company_id"] == str(_demo_company_id(db_session))

    # The new account must change the password before using the platform.
    login = client.post(
        "/api/v1/auth/login",
        json={"email": data["email"], "password": "temp-pass-123"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True


def test_create_user_duplicate_and_weak_password(client, db_session):
    from app.core.config import settings

    dup = client.post(
        "/api/v1/users",
        json={
            "email": settings.seed_admin_email,
            "password": "whatever-123",
            "role": "manager",
        },
    )
    assert dup.status_code == 409

    weak = client.post(
        "/api/v1/users",
        json={"email": "weak@example.com", "password": "short", "role": "manager"},
    )
    assert weak.status_code == 400

    bad_role = client.post(
        "/api/v1/users",
        json={"email": "bad@example.com", "password": "strong-pass-1", "role": "hacker"},
    )
    assert bad_role.status_code == 422


def test_patch_user_updates_role_and_name(client, db_session):
    from app.services.user_service import UserService
    from tests.test_analytics import _demo_company_id

    created = UserService(db_session).create(
        email=f"patch-{uuid.uuid4().hex[:8]}@example.com",
        password="strong-pass-1",
        full_name="До",
        role="manager",
        company_id=_demo_company_id(db_session),
    )
    db_session.commit()

    resp = client.patch(
        f"/api/v1/users/{created.id}",
        json={"full_name": "После", "role": "admin"},
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "После"
    assert resp.json()["role"] == "admin"


def test_disable_and_reset_password(client, db_session):
    from app.services.user_service import UserService
    from tests.test_analytics import _demo_company_id

    created = UserService(db_session).create(
        email=f"mgmt-{uuid.uuid4().hex[:8]}@example.com",
        password="strong-pass-1",
        full_name="Менеджер",
        role="manager",
        company_id=_demo_company_id(db_session),
    )
    db_session.commit()

    disabled = client.post(f"/api/v1/users/{created.id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    # Disabled accounts can no longer log in.
    login = client.post(
        "/api/v1/auth/login",
        json={"email": created.email, "password": "strong-pass-1"},
    )
    assert login.status_code == 401

    reset = client.post(
        f"/api/v1/users/{created.id}/reset-password",
        json={"new_password": "fresh-temp-456"},
    )
    assert reset.status_code == 200
    assert reset.json()["must_change_password"] is True

    # Re-enable so the account can log in with the fresh temp password.
    client.patch(f"/api/v1/users/{created.id}", json={"is_active": True})
    login = client.post(
        "/api/v1/auth/login",
        json={"email": created.email, "password": "fresh-temp-456"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["must_change_password"] is True


def test_audit_records_user_management(client, db_session):
    from app.services.user_service import UserService
    from tests.test_analytics import _demo_company_id

    created = UserService(db_session).create(
        email=f"aud-{uuid.uuid4().hex[:8]}@example.com",
        password="strong-pass-1",
        full_name="Аудит",
        role="manager",
        company_id=_demo_company_id(db_session),
    )
    db_session.commit()
    client.post(f"/api/v1/users/{created.id}/disable")
    client.post(
        f"/api/v1/users/{created.id}/reset-password",
        json={"new_password": "fresh-temp-456"},
    )

    actions = {e["action"] for e in client.get("/api/v1/audit").json()["items"]}
    assert "user.disable" in actions
    assert "user.reset_password" in actions
