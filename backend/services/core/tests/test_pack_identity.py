"""Sprint 5.9.1 DoD: per-pack identity, service tokens, dispatch tokens."""

from __future__ import annotations

import uuid

import jwt
import pytest
from shared.pack_security import (
    load_dispatch_secret as pack_load_dispatch_secret,
)
from shared.pack_security import (
    verify_core_dispatch_token,
)
from sqlalchemy import select

from app.core.config import settings
from app.models import PackIdentity, PackIdentityStatus
from app.services.pack_identity_service import (
    PackIdentityError,
    PackIdentityService,
    generate_pack_secret,
    load_dispatch_secret,
    verify_internal_service_token,
)


@pytest.fixture
def identity_svc(db_session):
    return PackIdentityService(db_session)


def _provision(db_session, svc, name):
    result = svc.provision(name)
    db_session.commit()
    return result


# --- secret generation -------------------------------------------------------


def test_generated_secrets_have_prefix_and_entropy(db_session):
    secret = generate_pack_secret("autoparts", "bootstrap")
    assert secret.startswith("autoparts_bootstrap_sec_")
    assert len(secret) >= 40  # 43-char urlsafe payload + prefix


def test_different_packs_get_different_secrets(db_session, identity_svc):
    ap = _provision(db_session, identity_svc, "autoparts")
    be = _provision(db_session, identity_svc, "beauty")
    assert ap["bootstrap_secret"] != be["bootstrap_secret"]
    assert ap["dispatch_secret"] != be["dispatch_secret"]


def test_no_plaintext_in_db(db_session, identity_svc):
    result = _provision(db_session, identity_svc, "autoparts")
    row = db_session.scalars(select(PackIdentity)).first()
    assert result["bootstrap_secret"] not in (row.bootstrap_secret_hash or "")
    assert result["dispatch_secret"] not in (row.dispatch_secret_hash or "")


# --- token endpoint ----------------------------------------------------------


def test_bootstrap_secret_obtains_service_token(client, db_session, identity_svc):
    result = _provision(db_session, identity_svc, "autoparts")
    resp = client.post(
        "/internal/token",
        headers={
            "X-Pack-Id": "autoparts",
            "X-Pack-Credential": result["bootstrap_secret"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "Bearer"
    claims = verify_internal_service_token(data["access_token"])
    assert claims is not None
    assert claims["sub"] == "pack:autoparts"
    assert claims["aud"] == "agentos-internal"
    # Service token proves identity only — never tenant scope.
    assert "tenant_id" not in claims
    assert "permissions" not in claims


def test_wrong_secret_is_401(client, db_session, identity_svc):
    _provision(db_session, identity_svc, "autoparts")
    resp = client.post(
        "/internal/token",
        headers={"X-Pack-Id": "autoparts", "X-Pack-Credential": "autoparts_bootstrap_sec_wrong"},
    )
    assert resp.status_code == 401


def test_beauty_secret_claiming_autoparts_is_401(client, db_session, identity_svc):
    """A stolen Beauty credential cannot authenticate as AutoParts."""
    be = _provision(db_session, identity_svc, "beauty")
    resp = client.post(
        "/internal/token",
        headers={"X-Pack-Id": "autoparts", "X-Pack-Credential": be["bootstrap_secret"]},
    )
    assert resp.status_code == 401


def test_rotation_invalidates_old_secret_and_bumps_version(db_session, identity_svc):
    first = _provision(db_session, identity_svc, "autoparts")
    second = _provision(db_session, identity_svc, "autoparts")
    assert second["credential_version"] == first["credential_version"] + 1

    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        identity_svc.authenticate("autoparts", first["bootstrap_secret"])
    identity = identity_svc.authenticate("autoparts", second["bootstrap_secret"])
    assert identity.credential_version == second["credential_version"]


def test_revoked_identity_cannot_get_tokens(db_session, identity_svc):
    result = _provision(db_session, identity_svc, "autoparts")
    identity_svc.set_status("autoparts", PackIdentityStatus.revoked)
    db_session.commit()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        identity_svc.authenticate("autoparts", result["bootstrap_secret"])
    assert "PACK_REVOKED" in str(excinfo.value.detail)


def test_disabled_identity_rejects_authentication(db_session, identity_svc):
    result = _provision(db_session, identity_svc, "autoparts")
    identity_svc.set_status("autoparts", PackIdentityStatus.disabled)
    db_session.commit()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        identity_svc.authenticate("autoparts", result["bootstrap_secret"])
    assert "PACK_DISABLED" in str(excinfo.value.detail)


def test_revoked_identity_blocks_provisioning(db_session, identity_svc):
    _provision(db_session, identity_svc, "autoparts")
    identity_svc.set_status("autoparts", PackIdentityStatus.revoked)
    with pytest.raises(PackIdentityError):
        identity_svc.provision("autoparts")


def test_stale_credential_version_token_is_rejected(db_session, identity_svc):
    result = _provision(db_session, identity_svc, "autoparts")
    token, _ = identity_svc.issue_service_token(identity_svc.get("autoparts"))
    claims = jwt.decode(
        token,
        settings.internal_jwt_key,
        algorithms=["HS256"],
        issuer="agentos-core",
        audience="agentos-internal",
    )
    assert claims["credential_version"] == result["credential_version"]
    # Rotation bumps the DB version; previously issued tokens no longer match.
    _provision(db_session, identity_svc, "autoparts")
    assert not identity_svc.verify_credential_version(claims)
    fresh_token, _ = identity_svc.issue_service_token(identity_svc.get("autoparts"))
    fresh_claims = jwt.decode(
        fresh_token,
        settings.internal_jwt_key,
        algorithms=["HS256"],
        issuer="agentos-core",
        audience="agentos-internal",
    )
    assert identity_svc.verify_credential_version(fresh_claims)


# --- dispatch tokens ---------------------------------------------------------


def test_dispatch_token_accepted_by_own_pack_rejected_by_other(tmp_path, db_session, identity_svc, monkeypatch):
    ap = _provision(db_session, identity_svc, "autoparts")
    be = _provision(db_session, identity_svc, "beauty")
    # Both packs' dispatch material mounted where core signs from.
    (tmp_path / "autoparts-dispatch").write_text(ap["dispatch_secret"])
    (tmp_path / "beauty-dispatch").write_text(be["dispatch_secret"])
    monkeypatch.setattr(settings, "pack_secrets_dir", str(tmp_path))

    token = identity_svc.issue_dispatch_token(
        "autoparts", tenant_id=str(uuid.uuid4()), task_id=str(uuid.uuid4()), dispatch_id=str(uuid.uuid4())
    )
    assert token is not None

    # Own pack accepts.
    ap_key = pack_load_dispatch_secret("autoparts", secrets_dir=str(tmp_path))
    claims = verify_core_dispatch_token(token, expected_pack="autoparts", key=ap_key)
    assert claims["aud"] == "pack:autoparts"
    assert claims["sub"] == "pack:autoparts"

    # The same token presented to Beauty fails the audience check.
    be_key = pack_load_dispatch_secret("beauty", secrets_dir=str(tmp_path))
    with pytest.raises(jwt.PyJWTError):
        verify_core_dispatch_token(token, expected_pack="beauty", key=be_key)


def test_dispatch_token_without_mounted_material_is_none(db_session, identity_svc, monkeypatch):
    monkeypatch.setattr(settings, "pack_secrets_dir", str(uuid.uuid4()))
    assert identity_svc.issue_dispatch_token("ghost-pack") is None


def test_dispatch_secret_file_loader_reads_mounted_file(db_session, identity_svc, tmp_path, monkeypatch):
    result = _provision(db_session, identity_svc, "autoparts")
    (tmp_path / "autoparts-dispatch").write_text(result["dispatch_secret"])
    monkeypatch.setattr(settings, "pack_secrets_dir", str(tmp_path))
    assert load_dispatch_secret("autoparts") == result["dispatch_secret"]
    # Unknown pack → no material.
    assert load_dispatch_secret("ghost") is None


# --- lifecycle wiring --------------------------------------------------------


def test_identity_survives_restart_semantics(db_session, identity_svc):
    """Identity rows persist independently of the packs table."""
    _provision(db_session, identity_svc, "autoparts")
    identity = identity_svc.get("autoparts")
    assert identity.credential_version == 1
    assert identity.created_at is not None
    assert identity.status == PackIdentityStatus.active
