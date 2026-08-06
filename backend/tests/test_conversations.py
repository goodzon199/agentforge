from __future__ import annotations

import pytest

from sqlalchemy import select


def _demo_company_id(db_session):
    from app.models import Company

    return db_session.scalars(select(Company)).first().id


# --- Customers -------------------------------------------------------------

def test_create_customer(client, db_session):
    resp = client.post(
        "/api/v1/customers",
        json={
            "company_id": str(_demo_company_id(db_session)),
            "name": "Иван Петров",
            "phone": "+7 900 123-45-67",
            "email": "ivan@example.com",
            "source": "web",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Иван Петров"
    assert data["source"] == "web"
    assert data["company_id"] == str(_demo_company_id(db_session))


def test_list_customers(client, db_session):
    client.post(
        "/api/v1/customers",
        json={"company_id": str(_demo_company_id(db_session)), "name": "Иван"},
    )
    resp = client.get("/api/v1/customers")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# --- Conversations ---------------------------------------------------------

def _make_customer(client, db_session):
    resp = client.post(
        "/api/v1/customers",
        json={"company_id": str(_demo_company_id(db_session)), "name": "Иван"},
    )
    return resp.json()["id"]


def test_create_conversation(client, db_session):
    customer_id = _make_customer(client, db_session)
    resp = client.post(
        "/api/v1/conversations",
        json={
            "company_id": str(_demo_company_id(db_session)),
            "customer_id": customer_id,
            "channel": "web",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "open"
    assert data["customer_name"] == "Иван"


def test_create_conversation_missing_customer(client, db_session):
    import uuid

    resp = client.post(
        "/api/v1/conversations",
        json={
            "company_id": str(_demo_company_id(db_session)),
            "customer_id": str(uuid.uuid4()),
            "channel": "web",
        },
    )
    assert resp.status_code == 404


def test_list_and_get_conversation(client, db_session):
    customer_id = _make_customer(client, db_session)
    created = client.post(
        "/api/v1/conversations",
        json={
            "company_id": str(_demo_company_id(db_session)),
            "customer_id": customer_id,
        },
    ).json()

    listing = client.get("/api/v1/conversations")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = client.get(f"/api/v1/conversations/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    missing = client.get("/api/v1/conversations/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


# --- Messages --------------------------------------------------------------

def test_send_message_creates_message_and_task(client, db_session):
    import uuid

    from app.models import Task

    customer_id = _make_customer(client, db_session)
    conversation_id = client.post(
        "/api/v1/conversations",
        json={
            "company_id": str(_demo_company_id(db_session)),
            "customer_id": customer_id,
        },
    ).json()["id"]

    resp = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны передние колодки на BMW X5 2019"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["message"]["content"].startswith("Нужны передние колодки")
    assert data["message"]["sender_type"] == "customer"
    assert data["task_id"] is not None

    # Auto-created task is linked to the conversation/message.
    task = db_session.scalars(
        select(Task).where(Task.id == uuid.UUID(data["task_id"]))
    ).first()
    assert task is not None
    assert task.objective == "process_customer_message"
    assert task.input_data["conversation_id"] == conversation_id
    assert task.input_data["message_id"] == data["message"]["id"]


def test_list_messages(client, db_session):
    customer_id = _make_customer(client, db_session)
    conversation_id = client.post(
        "/api/v1/conversations",
        json={
            "company_id": str(_demo_company_id(db_session)),
            "customer_id": customer_id,
        },
    ).json()["id"]

    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "привет"},
    )
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "agent", "content": "здравствуйте"},
    )

    resp = client.get(f"/api/v1/conversations/{conversation_id}/messages")
    assert resp.status_code == 200
    messages = resp.json()
    # The customer message triggers IntakeAgent, which replies automatically.
    assert messages[0]["content"] == "привет"
    assert messages[0]["sender_type"] == "customer"
    assert messages[-1]["content"] == "здравствуйте"
    assert messages[-1]["sender_type"] == "agent"

    # Agent messages do not create processing tasks.
    for message in messages:
        if message["sender_type"] == "agent":
            assert message["task_id"] is None


def test_message_in_missing_conversation(client, db_session):
    import uuid

    resp = client.post(
        f"/api/v1/conversations/{uuid.uuid4()}/messages",
        json={"sender_type": "customer", "content": "hi"},
    )
    assert resp.status_code == 404
