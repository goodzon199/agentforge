from __future__ import annotations

import pytest


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
        json={"email": "admin@agentos.local", "password": "admin123"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "admin@agentos.local"
    assert data["user"]["is_superuser"] is True


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
        json={"email": "admin@agentos.local", "password": "admin123"},
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
