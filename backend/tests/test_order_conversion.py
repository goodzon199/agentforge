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
    """Price + send + approve -> returns (quote_id, conversation_id, draft_text)."""
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


def _status(client, quote_id) -> str:
    return client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()["status"]


def test_accept_sent_quote(client, db_session):
    quote_id, conversation_id, _ = _sent_quote(client, db_session)

    resp = client.post(f"/api/v1/quotes/{quote_id}/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert _status(client, quote_id) == "accepted"

    actions = client.get("/api/v1/actions").json()
    accepts = [a for a in actions if a["action_type"] == "accept_quote"]
    assert len(accepts) == 1
    assert accepts[0]["risk_level"] == "LOW"
    assert accepts[0]["status"] == "executed"


def test_accept_not_sent_conflict(client, db_session):
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    quote_id = client.post(f"/api/v1/part_requests/{pr.id}/price").json()["quote_id"]

    resp = client.post(f"/api/v1/quotes/{quote_id}/accept")
    assert resp.status_code == 409


def test_accept_idempotent(client, db_session):
    quote_id, conversation_id, _ = _sent_quote(client, db_session)
    client.post(f"/api/v1/quotes/{quote_id}/accept")
    again = client.post(f"/api/v1/quotes/{quote_id}/accept")
    assert again.status_code == 200
    assert again.json()["already_accepted"] is True


def test_convert_from_sent_creates_order(client, db_session):
    quote_id, conversation_id, _ = _sent_quote(client, db_session)

    resp = client.post(f"/api/v1/quotes/{quote_id}/convert")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "converted_to_order"
    assert data["already_converted"] is False
    assert data["order_number"].startswith("ORD-")
    order_id = data["order_id"]

    assert _status(client, quote_id) == "converted_to_order"

    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["order_number"] == data["order_number"]
    assert order["status"] == "new"
    assert order["quote_id"] == quote_id
    assert order["order_total"] == "7930.00"
    assert len(order["items"]) == 2

    # The customer sees a confirmation in the dialog.
    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    orders_msgs = [
        m
        for m in detail["messages"]
        if m["sender_type"] == "agent"
        and (m.get("structured_data") or {}).get("kind") == "order"
    ]
    assert len(orders_msgs) == 1
    assert data["order_number"] in orders_msgs[0]["content"]

    # create_order is audited as a HIGH-risk human action.
    actions = client.get("/api/v1/actions").json()
    creates = [a for a in actions if a["action_type"] == "create_order"]
    assert len(creates) == 1
    assert creates[0]["risk_level"] == "HIGH"
    assert creates[0]["status"] == "executed"


def test_convert_idempotent(client, db_session):
    quote_id, conversation_id, _ = _sent_quote(client, db_session)
    first = client.post(f"/api/v1/quotes/{quote_id}/convert").json()
    again = client.post(f"/api/v1/quotes/{quote_id}/convert").json()
    assert again["already_converted"] is True
    assert again["order_id"] == first["order_id"]


def test_convert_draft_conflict(client, db_session):
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    quote_id = client.post(f"/api/v1/part_requests/{pr.id}/price").json()["quote_id"]

    resp = client.post(f"/api/v1/quotes/{quote_id}/convert")
    assert resp.status_code == 409


def test_convert_manager_only(client, db_session):
    quote_id, conversation_id, _ = _sent_quote(client, db_session)

    from app.core.config import settings
    from app.models import User

    admin = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()
    admin.is_superuser = False
    db_session.commit()

    resp = client.post(f"/api/v1/quotes/{quote_id}/convert")
    assert resp.status_code == 403
    admin.is_superuser = True
    db_session.commit()


def test_auto_accept_on_positive_customer_reply(client, db_session):
    quote_id, conversation_id, _ = _sent_quote(client, db_session)

    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Да, беру этот вариант"},
    )
    assert _status(client, quote_id) == "accepted"


def test_auto_accept_ignores_negation(client, db_session):
    quote_id, conversation_id, _ = _sent_quote(client, db_session)

    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нет, не подходит, слишком дорого"},
    )
    assert _status(client, quote_id) == "sent"


def test_auto_accept_only_for_sent_quote(client, db_session):
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    quote_id = client.post(f"/api/v1/part_requests/{pr.id}/price").json()["quote_id"]

    # Quote is still a draft — a "беру" reply must NOT accept it.
    client.post(
        f"/api/v1/conversations/{pr.conversation_id}/messages",
        json={"sender_type": "customer", "content": "Да, беру"},
    )
    assert _status(client, quote_id) == "draft"


def test_orders_scoped_and_404(client, db_session):
    from app.models import Company, Order

    other = Company(name="Другая компания", slug="other-company")
    db_session.add(other)
    db_session.commit()
    order = Order(
        company_id=other.id,
        conversation_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        part_request_id=uuid.uuid4(),
        order_number="ORD-OTHER-1",
        items=[],
    )
    db_session.add(order)
    db_session.commit()

    ids = [o["id"] for o in client.get("/api/v1/orders").json()]
    assert str(order.id) not in ids
    assert client.get(f"/api/v1/orders/{order.id}").status_code == 403
    assert client.get(f"/api/v1/orders/{uuid.uuid4()}").status_code == 404
