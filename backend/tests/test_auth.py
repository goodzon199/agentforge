from __future__ import annotations

import pytest

from tests.conftest import TEST_ADMIN_PASSWORD


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


def test_login_returns_token_and_user(auth_client):
    resp = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@agentos.local", "password": TEST_ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "admin@agentos.local"
    assert data["user"]["is_superuser"] is True
    assert data["user"]["must_change_password"] is False


def test_login_wrong_password(auth_client):
    resp = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@agentos.local", "password": "wrong"},
    )
    assert resp.status_code == 401


def test_protected_route_requires_token(auth_client):
    resp = auth_client.get("/api/v1/companies")
    assert resp.status_code == 401


def test_me_with_valid_token(auth_client):
    login = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@agentos.local", "password": TEST_ADMIN_PASSWORD},
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    me = auth_client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "admin@agentos.local"

    companies = auth_client.get("/api/v1/companies", headers=headers)
    assert companies.status_code == 200


def test_me_with_garbage_token(auth_client):
    resp = auth_client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"}
    )
    assert resp.status_code == 401


def test_change_password_updates_and_clears_flag(db_session, auth_client):

    from app.models import User

    # A temporary account (e.g. production bootstrap admin) must change the
    # password before it can use anything except /auth/me and change-password.
    temp = User(
        email="temp-boot@agentos.local",
        full_name="Temp admin",
        is_active=True,
        hashed_password="",
        is_superuser=True,
        must_change_password=True,
    )
    from app.core.security import hash_password

    temp.hashed_password = hash_password("temp-password-1")
    db_session.add(temp)
    db_session.commit()

    login = auth_client.post(
        "/api/v1/auth/login",
        json={"email": temp.email, "password": "temp-password-1"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Everything except /auth/me is blocked until the password is changed.
    assert auth_client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert auth_client.get("/api/v1/companies", headers=headers).status_code == 403

    # Wrong current password -> 400, flag stays.
    bad = auth_client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "nope", "new_password": "new-strong-pass-1"},
    )
    assert bad.status_code == 400

    changed = auth_client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "current_password": "temp-password-1",
            "new_password": "new-strong-pass-1",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["must_change_password"] is False

    # Now the account can use the platform with the new password.
    assert auth_client.get("/api/v1/companies", headers=headers).status_code == 200
    fresh_login = auth_client.post(
        "/api/v1/auth/login",
        json={"email": temp.email, "password": "new-strong-pass-1"},
    )
    assert fresh_login.status_code == 200
    assert fresh_login.json()["user"]["must_change_password"] is False


def test_change_password_requires_strength(db_session, auth_client):
    from app.core.security import hash_password
    from app.models import User

    temp = User(
        email="weak-flag@agentos.local",
        full_name="Weak",
        is_active=True,
        hashed_password=hash_password("temp-password-1"),
        is_superuser=False,
        must_change_password=True,
    )
    db_session.add(temp)
    db_session.commit()

    login = auth_client.post(
        "/api/v1/auth/login",
        json={"email": temp.email, "password": "temp-password-1"},
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}
    resp = auth_client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={"current_password": "temp-password-1", "new_password": "short"},
    )
    assert resp.status_code == 400


def test_security_password_roundtrip():
    from app.core.security import hash_password, verify_password

    hashed = hash_password("secret-pass")
    assert hashed != "secret-pass"
    assert verify_password("secret-pass", hashed) is True
    assert verify_password("wrong", hashed) is False
    assert verify_password("secret-pass", "garbage") is False


def test_token_roundtrip():
    import uuid

    from app.core.security import create_access_token, decode_access_token

    uid = uuid.uuid4()
    token = create_access_token(str(uid))
    assert decode_access_token(token) == uid
    assert decode_access_token("invalid") is None


def test_old_token_invalid_after_secret_change():
    """Tokens signed with the previous JWT_SECRET are rejected after rotation."""
    import uuid

    from app.core.config import settings
    from app.core.security import create_access_token, decode_access_token

    saved = settings.jwt_secret
    try:
        settings.jwt_secret = "a" * 64
        token = create_access_token(str(uuid.uuid4()))
        assert decode_access_token(token) is not None
        # Rotate the secret: the old token must now decode to None.
        settings.jwt_secret = "b" * 64
        assert decode_access_token(token) is None
    finally:
        settings.jwt_secret = saved
