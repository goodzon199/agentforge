from __future__ import annotations

import uuid

from sqlalchemy import select


def _company_id(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company

    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id


def _make_ready_part_request(db_session):
    from app.models.enums import PartRequestStatus
    from app.services.conversation_service import ConversationService
    from app.services.part_request_service import PartRequestService

    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=_company_id(db_session), name="Иван Петров")
    db_session.add(customer)
    db_session.flush()
    conversation = cs.create_conversation(
        company_id=_company_id(db_session), customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    pr = PartRequestService(db_session).create(
        company_id=_company_id(db_session),
        conversation_id=conversation.id,
        customer_id=customer.id,
        source_message_id=None,
        part_name="Тормозные колодки",
        article="",
        status=PartRequestStatus.ready_for_search,
    )
    db_session.add(pr)
    db_session.commit()
    return pr


def _sent_quote(client, db_session) -> tuple[str, str, str]:
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    price = client.post(f"/api/v1/part_requests/{pr.id}/price").json()
    quote_id = price["quote_id"]
    conversation_id = str(pr.conversation_id)

    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    send = client.post(
        f"/api/v1/quotes/{quote_id}/send", json={"message": draft["ai_draft"]}
    ).json()
    approve = client.post(f"/api/v1/approvals/{send['approval_id']}/approve")
    assert approve.status_code == 200
    return quote_id, conversation_id, draft["ai_draft"]


def _converted_order_id(client, db_session) -> str:
    quote_id, _conversation_id, _ = _sent_quote(client, db_session)
    data = client.post(f"/api/v1/quotes/{quote_id}/convert").json()
    return data["order_id"]


def _approve_purchase(client, db_session, order_id) -> dict:
    purchases = client.get(f"/api/v1/supplier-orders?order_id={order_id}").json()
    assert len(purchases) == 1
    resp = client.post(
        f"/api/v1/supplier-orders/{purchases[0]['approval_id']}/approve"
    )
    assert resp.status_code == 200
    return resp.json()


def _external_order_id(db_session, order_id) -> str:
    from app.models import SupplierFulfillment

    fulfillment = db_session.scalars(
        select(SupplierFulfillment).where(
            SupplierFulfillment.order_id == uuid.UUID(order_id)
        )
    ).first()
    assert fulfillment is not None and fulfillment.external_order_id
    return fulfillment.external_order_id


def _rewind_mock_order(db_session, order_id, seconds: float) -> None:
    """Simulate that the supplier's delivery window has already passed."""
    from app.suppliers import mock as mock_module

    ext = _external_order_id(db_session, order_id)
    assert ext in mock_module._MOCK_ORDERS
    mock_module._MOCK_ORDERS[ext]["placed_at"] -= seconds


def _conversation_messages(client, conversation_id):
    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    return [
        m
        for m in detail["messages"]
        if (m.get("structured_data") or {}).get("kind") == "order_notification"
    ]


def test_approve_starts_tracking_at_accepted(client, db_session):
    order_id = _converted_order_id(client, db_session)
    data = _approve_purchase(client, db_session, order_id)

    assert data["tracking_status"] == "accepted"
    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["tracking_status"] == "accepted"


def test_track_advances_to_arrived_and_raises_notification(client, db_session):
    order_id = _converted_order_id(client, db_session)
    _approve_purchase(client, db_session, order_id)
    _rewind_mock_order(db_session, order_id, 10 ** 9)

    resp = client.post(f"/api/v1/supplier-orders/{order_id}/track")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tracking_status"] == "arrived"
    assert data["suppliers"][0]["supplier_status"] == "arrived"
    assert data["notification"]["kind"] == "arrival"
    assert data["notification"]["status"] == "pending"

    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["tracking_status"] == "arrived"


def test_arrival_notification_approval_sends_customer_message(client, db_session):
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    quote_id = client.post(f"/api/v1/part_requests/{pr.id}/price").json()["quote_id"]
    conversation_id = str(pr.conversation_id)
    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    send = client.post(
        f"/api/v1/quotes/{quote_id}/send", json={"message": draft["ai_draft"]}
    ).json()
    approve = client.post(f"/api/v1/approvals/{send['approval_id']}/approve")
    assert approve.status_code == 200
    order_id = client.post(f"/api/v1/quotes/{quote_id}/convert").json()["order_id"]

    _approve_purchase(client, db_session, order_id)
    _rewind_mock_order(db_session, order_id, 10 ** 9)
    tracked = client.post(f"/api/v1/supplier-orders/{order_id}/track").json()
    approval_id = tracked["notification"]["approval_id"]

    resp = client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["message_sent"] is True

    messages = _conversation_messages(client, conversation_id)
    assert len(messages) == 1
    assert "прибыл" in messages[0]["content"]
    assert messages[0]["sender_type"] == "agent"


def test_arrival_notification_low_policy_auto_sends(client, db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company

    order_id, conversation_id, _ = _sent_quote(client, db_session)
    order_id = client.post(f"/api/v1/quotes/{order_id}/convert").json()["order_id"]
    _approve_purchase(client, db_session, order_id)
    _rewind_mock_order(db_session, order_id, 10 ** 9)

    company = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    company.settings = {"permissions": {"send_customer_message": "low"}}
    db_session.commit()

    tracked = client.post(f"/api/v1/supplier-orders/{order_id}/track").json()
    assert tracked["tracking_status"] == "arrived"
    assert tracked["notification"]["status"] == "sent"
    assert tracked["notification"]["message_sent"] is True

    messages = _conversation_messages(client, conversation_id)
    assert len(messages) == 1
    assert "прибыл" in messages[0]["content"]

    # No approval was raised for the arrival.
    approvals = client.get("/api/v1/approvals").json()
    notifications = [
        a for a in approvals if (a.get("payload") or {}).get("kind") == "order_notification"
    ]
    assert notifications == []


def test_notification_raised_once(client, db_session):
    order_id, _conversation_id, _ = _sent_quote(client, db_session)
    order_id = client.post(f"/api/v1/quotes/{order_id}/convert").json()["order_id"]
    _approve_purchase(client, db_session, order_id)
    _rewind_mock_order(db_session, order_id, 10 ** 9)

    first = client.post(f"/api/v1/supplier-orders/{order_id}/track").json()
    again = client.post(f"/api/v1/supplier-orders/{order_id}/track").json()
    assert again["notification"] is None

    approvals = client.get("/api/v1/approvals").json()
    notifications = [
        a for a in approvals if (a.get("payload") or {}).get("kind") == "order_notification"
    ]
    assert len(notifications) == 1
    assert first["notification"]["approval_id"] == str(notifications[0]["id"])


def test_hand_over_from_arrived(client, db_session):
    order_id = _converted_order_id(client, db_session)
    _approve_purchase(client, db_session, order_id)
    _rewind_mock_order(db_session, order_id, 10 ** 9)
    client.post(f"/api/v1/supplier-orders/{order_id}/track")

    resp = client.post(f"/api/v1/supplier-orders/{order_id}/hand-over")
    assert resp.status_code == 200
    assert resp.json()["tracking_status"] == "handed_over"

    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["tracking_status"] == "handed_over"

    # Handing over twice is idempotent.
    again = client.post(f"/api/v1/supplier-orders/{order_id}/hand-over").json()
    assert again["already_handed_over"] is True


def test_hand_over_not_arrived_conflict(client, db_session):
    order_id = _converted_order_id(client, db_session)
    _approve_purchase(client, db_session, order_id)

    resp = client.post(f"/api/v1/supplier-orders/{order_id}/hand-over")
    assert resp.status_code == 409


def test_order_detail_refreshes_tracking(client, db_session):
    order_id = _converted_order_id(client, db_session)
    _approve_purchase(client, db_session, order_id)
    _rewind_mock_order(db_session, order_id, 10 ** 9)

    # Reading the order polls the supplier adapter and updates tracking.
    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["tracking_status"] == "arrived"


def test_hand_over_manager_only(client, db_session):
    from app.core.config import settings
    from app.models import User

    order_id = _converted_order_id(client, db_session)
    _approve_purchase(client, db_session, order_id)
    _rewind_mock_order(db_session, order_id, 10 ** 9)
    client.post(f"/api/v1/supplier-orders/{order_id}/track")

    admin = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()
    admin.is_superuser = False
    db_session.commit()

    resp = client.post(f"/api/v1/supplier-orders/{order_id}/hand-over")
    assert resp.status_code == 403
    admin.is_superuser = True
    db_session.commit()
