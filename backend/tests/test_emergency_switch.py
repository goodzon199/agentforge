from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.emergency import EmergencySwitch


@pytest.fixture
def switch():
    s = EmergencySwitch()
    s.release()  # start from a clean slate
    yield s
    s.release()  # never leak an engaged switch into other tests


# --- Unit behaviour ----------------------------------------------------------


def test_engage_and_release_roundtrip(switch):
    assert switch.is_engaged() is False
    switch.engage("   отладка после инцидента   ")
    assert switch.is_engaged() is True
    status = switch.status()
    assert status["engaged"] is True
    assert status["reason"] == "отладка после инцидента"
    switch.release()
    assert switch.is_engaged() is False
    assert switch.status()["reason"] is None


def test_release_without_engage_is_noop(switch):
    switch.release()
    assert switch.is_engaged() is False


# --- API: status / engage / release -----------------------------------------


def test_emergency_status_default(client):
    resp = client.get("/api/v1/ops/emergency")
    assert resp.status_code == 200
    assert resp.json() == {"engaged": False, "reason": None, "engaged_at": None}


def test_emergency_engage_and_release_via_api(client, db_session):
    resp = client.post("/api/v1/ops/emergency/engage", json={"reason": "тестовый инцидент"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["engaged"] is True
    assert body["reason"] == "тестовый инцидент"

    # The switch is really on (not just the HTTP view).
    from app.core.emergency import emergency_switch

    assert emergency_switch.is_engaged() is True

    # Engage/release are recorded in the audit journal.
    from app.models import AuditEvent

    events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "emergency.engage")
    ).all()
    assert len(events) == 1

    resp = client.post("/api/v1/ops/emergency/release")
    assert resp.status_code == 200
    assert resp.json()["engaged"] is False
    assert emergency_switch.is_engaged() is False


def test_emergency_engage_requires_manager(client, db_session):
    from app.core.config import settings
    from app.models import User

    admin = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()
    saved_role = admin.role
    saved_superuser = admin.is_superuser
    admin.role = "viewer"
    admin.is_superuser = False
    try:
        resp = client.post(
            "/api/v1/ops/emergency/engage", json={"reason": "не должен пройти"}
        )
        assert resp.status_code == 403
    finally:
        admin.role = saved_role
        admin.is_superuser = saved_superuser


# --- Enforcement -------------------------------------------------------------


def test_task_create_blocked_when_engaged(client, db_session):
    from app.core.emergency import emergency_switch

    emergency_switch.engage("инцидент")
    try:
        from app.models import Company

        company = db_session.scalars(select(Company)).first()
        resp = client.post(
            "/api/v1/tasks",
            json={
                "company_id": str(company.id),
                "title": "Задача во время остановки",
                "objective": "search_parts",
            },
        )
        assert resp.status_code == 503
    finally:
        emergency_switch.release()

    # After release the same task is accepted.
    resp = client.post(
        "/api/v1/tasks",
        json={
            "company_id": str(company.id),
            "title": "Задача после остановки",
            "objective": "search_parts",
        },
    )
    assert resp.status_code == 201


def test_public_chat_blocked_when_engaged(client, db_session):
    from app.core.emergency import emergency_switch

    emergency_switch.engage("инцидент")
    try:
        from app.core.seeding import DEMO_COMPANY_SLUG
        from app.models import Company

        company = db_session.scalars(
            select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
        ).first()
        resp = client.post(
            "/api/v1/public/chat/start",
            json={
                "public_token": company.public_token,
                "visitor_name": "Гость",
                "client_key": f"emg-{uuid.uuid4().hex[:8]}",
            },
        )
        assert resp.status_code == 503
    finally:
        emergency_switch.release()
