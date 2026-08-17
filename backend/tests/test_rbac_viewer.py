from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.seeding import DEMO_COMPANY_SLUG
from app.models import Company, PartRequest, User
from app.models.enums import PartRequestStatus


def _company_id(db_session):
    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id


def _viewer(db_session, company_id):
    user = User(
        email=f"viewer.rbac.{uuid.uuid4().hex[:8]}@example.com",
        full_name="Зритель",
        is_active=True,
        company_id=company_id,
        role="viewer",
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def viewer_client(client, db_session):
    """A TestClient whose current user is a read-only viewer of the demo company."""
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.core.database import get_db
    from app.main import app

    viewer = _viewer(db_session, _company_id(db_session))

    def override_get_db():
        yield db_session

    def override_get_current_user():
        return viewer

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _part_request(db_session, company_id):
    from app.services.conversation_service import ConversationService

    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=company_id, name="Иван Петров")
    db_session.add(customer)
    db_session.flush()
    conversation = cs.create_conversation(
        company_id=company_id, customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    pr = PartRequest(
        company_id=company_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        part_name="Тормозные колодки",
        article="GDB3410",
        quantity=1,
        status=PartRequestStatus.ready_for_search,
        missing_fields=[],
        structured_data={"intent_confidence": 0.9},
    )
    db_session.add(pr)
    db_session.flush()
    return pr


def test_viewer_can_read_fitment_explain(client, db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id)
    resp = client.get(f"/api/v1/fitment/{pr.id}/explain")
    assert resp.status_code == 200


def test_viewer_cannot_verify_fitment(viewer_client, db_session):
    company_id = _company_id(db_session)
    pr = _part_request(db_session, company_id)
    resp = viewer_client.post(
        f"/api/v1/fitment/{pr.id}/verify",
        json={"article": "GDB3410", "brand": "TRW", "result": "confirmed"},
    )
    assert resp.status_code == 403


def test_viewer_can_read_orders(viewer_client, db_session):
    from app.services.order_service import OrderService

    company_id = _company_id(db_session)
    orders = OrderService(db_session).list_orders(company_id=company_id)
    assert viewer_client.get("/api/v1/orders").status_code == 200
    if orders:
        assert (
            viewer_client.get(f"/api/v1/orders/{orders[0].id}").status_code == 200
        )


def test_viewer_cannot_convert_quote(client, db_session):
    """No quote exists yet — the gating must reject the call before quote work."""
    company_id = _company_id(db_session)
    from app.api.access import ensure_writer

    viewer = _viewer(db_session, company_id)
    with pytest.raises(Exception) as excinfo:
        ensure_writer(viewer)
    assert excinfo.value.status_code == 403


def test_viewer_is_writer_false_and_manager_true(client, db_session):
    from app.api.access import is_writer

    company_id = _company_id(db_session)
    viewer = _viewer(db_session, company_id)
    assert is_writer(viewer) is False

    from app.services.user_service import UserService

    manager = UserService(db_session).create(
        email=f"mgr.rbac.{uuid.uuid4().hex[:8]}@example.com",
        full_name="Менеджер",
        password="Passw0rd!",
        role="manager",
        company_id=company_id,
    )
    db_session.flush()
    assert is_writer(manager) is True
