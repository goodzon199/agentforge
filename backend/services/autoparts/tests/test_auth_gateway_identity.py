"""Gateway identity: JWT issued by core resolves the pack's shadow user.

User UUIDs are per-database, so a core-issued token (sub=core UUID) cannot be
looked up directly. The token carries an email claim; get_current_user falls
back to the local account by email and skips the core-owned first-login
password gate for that shadow identity.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.security import create_access_token, decode_access_token_claims


def _client(db_session) -> TestClient:
    """TestClient without entering its context manager: the app lifespan
    opens real connections (redis/db); dependency overrides are enough here,
    mirroring conftest.client."""
    from app.api.deps import get_current_user
    from app.core.database import get_db
    from app.core.redis import redis_client
    from app.main import app

    saved_enabled = redis_client._enabled
    redis_client._enabled = False

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _hello(client: TestClient, token: str):
    return client.get(
        "/api/v1/hellopack/hello",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_claims_roundtrip_with_email(db_session):
    token = create_access_token(str(uuid.uuid4()), email="a@b.c")
    user_id, email = decode_access_token_claims(token)
    assert email == "a@b.c"
    assert decode_access_token_claims(create_access_token(str(user_id)))[1] is None


def test_core_issued_token_resolves_shadow_user_by_email(db_session):
    from sqlalchemy import select

    from app.core.config import settings
    from app.models import User

    admin = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()
    admin.must_change_password = True  # core owns this state; pack must not gate
    db_session.commit()

    # sub points to a user that exists only in core's database.
    foreign_sub = str(uuid.uuid4())
    token = create_access_token(foreign_sub, email=admin.email)

    response = _hello(_client(db_session), token)
    assert response.status_code == 200


def test_local_token_still_enforces_password_gate(db_session):
    from sqlalchemy import select

    from app.core.config import settings
    from app.models import User

    admin = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()
    admin.must_change_password = True
    db_session.commit()

    token = create_access_token(str(admin.id))
    response = _hello(_client(db_session), token)
    assert response.status_code == 403


def test_unknown_identity_without_email_claim_is_unauthorized(db_session):
    token = create_access_token(str(uuid.uuid4()))
    response = _hello(_client(db_session), token)
    assert response.status_code == 401
