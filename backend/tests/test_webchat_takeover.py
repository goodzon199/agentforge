from __future__ import annotations

import uuid

from sqlalchemy import select


def _demo_company(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company

    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()


def _public_token(db_session) -> str:
    company = _demo_company(db_session)
    assert company.public_token
    return company.public_token


def _start_chat(client, db_session, name="Иван", client_key=""):
    return client.post(
        "/api/v1/public/chat/start",
        json={
            "public_token": _public_token(db_session),
            "visitor_name": name,
            "client_key": client_key,
        },
    )


def _make_conversation(client, db_session) -> str:
    company = _demo_company(db_session)
    customer = client.post(
        "/api/v1/customers",
        json={"company_id": str(company.id), "name": "Клиент"},
    ).json()["id"]
    return client.post(
        "/api/v1/conversations",
        json={"company_id": str(company.id), "customer_id": customer},
    ).json()["id"]


def _agent_reply_count(client, conversation_id) -> int:
    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    return sum(1 for m in detail["messages"] if m["sender_type"] == "agent")


# --- Public web-chat channel ------------------------------------------------


def test_public_chat_start_resumes_same_conversation(client, db_session):
    first = _start_chat(client, db_session)
    assert first.status_code == 200
    data = first.json()
    assert data["conversation_id"]
    assert data["client_key"]
    assert data["channel"] == "webchat"
    assert data["mode"] == "ai_active"

    resumed = _start_chat(client, db_session, client_key=data["client_key"])
    assert resumed.status_code == 200
    assert resumed.json()["conversation_id"] == data["conversation_id"]
    assert resumed.json()["customer_id"] == data["customer_id"]


def test_public_chat_unknown_token_404(client, db_session):
    resp = client.post(
        "/api/v1/public/chat/start",
        json={"public_token": "no-such-token", "visitor_name": "Гость"},
    )
    assert resp.status_code == 404


def test_public_chat_full_pipeline_reply(client, db_session):
    started = _start_chat(client, db_session).json()
    conversation_id = started["conversation_id"]

    sent = client.post(
        "/api/v1/public/chat/messages",
        json={
            "conversation_id": conversation_id,
            "content": "Нужны передние колодки на BMW X5 2019",
        },
    )
    assert sent.status_code == 201
    assert sent.json()["task_id"] is not None

    messages = client.get(f"/api/v1/public/chat/{conversation_id}/messages").json()
    assert messages["mode"] == "ai_active"
    texts = [m["content"] for m in messages["messages"] if m["sender_type"] == "agent"]
    assert any("VIN" in t for t in texts)

    # The same pipeline produced a structured PartRequest.
    requests = client.get(
        f"/api/v1/part_requests?conversation_id={conversation_id}"
    ).json()
    assert len(requests) == 1


def test_public_chat_forbids_regular_conversation(client, db_session):
    conversation_id = _make_conversation(client, db_session)
    resp = client.post(
        "/api/v1/public/chat/messages",
        json={"conversation_id": conversation_id, "content": "Привет"},
    )
    assert resp.status_code == 403

    resp = client.get(f"/api/v1/public/chat/{conversation_id}/messages")
    assert resp.status_code == 403


# --- Human takeover ---------------------------------------------------------


def test_takeover_silences_agent_and_manager_replies(client, db_session):
    conversation_id = _make_conversation(client, db_session)

    msg = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны колодки на BMW X5 2019"},
    )
    assert msg.status_code == 201
    assert msg.json()["task_id"] is not None
    assert _agent_reply_count(client, conversation_id) == 1

    # Manager takes over -> mode flips to human_active.
    taken = client.post(f"/api/v1/conversations/{conversation_id}/takeover")
    assert taken.status_code == 200
    assert taken.json()["mode"] == "human_active"

    # Customer writes again: message is stored, but NO task and NO agent reply.
    silenced = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Подскажите сроки доставки"},
    )
    assert silenced.status_code == 201
    assert silenced.json()["task_id"] is None
    assert _agent_reply_count(client, conversation_id) == 1

    # Manager replies from the same dialog -> message lands for the customer.
    manager = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "manager", "content": "Доставка 2 дня, TRW есть в наличии"},
    )
    assert manager.status_code == 201
    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    manager_msgs = [m for m in detail["messages"] if m["sender_type"] == "manager"]
    assert len(manager_msgs) == 1

    # Give the conversation back to the AI -> processing resumes.
    released = client.post(f"/api/v1/conversations/{conversation_id}/release")
    assert released.status_code == 200
    assert released.json()["mode"] == "ai_active"

    resumed = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Вот VIN WBAKS410900H12345"},
    )
    assert resumed.json()["task_id"] is not None


def test_paused_and_closed_silence_agent(client, db_session):
    conversation_id = _make_conversation(client, db_session)
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны колодки на BMW X5 2019"},
    )
    assert _agent_reply_count(client, conversation_id) == 1

    paused = client.post(f"/api/v1/conversations/{conversation_id}/pause")
    assert paused.json()["mode"] == "paused"
    msg = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Ещё вопрос"},
    )
    assert msg.json()["task_id"] is None
    assert _agent_reply_count(client, conversation_id) == 1

    closed = client.post(f"/api/v1/conversations/{conversation_id}/close")
    assert closed.json()["mode"] == "closed"
    msg = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Что с заказом?"},
    )
    assert msg.json()["task_id"] is None
    assert _agent_reply_count(client, conversation_id) == 1

    reopened = client.post(f"/api/v1/conversations/{conversation_id}/reopen")
    assert reopened.json()["mode"] == "ai_active"
    msg = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Вот VIN WBAKS410900H12345"},
    )
    assert msg.json()["task_id"] is not None


def test_takeover_company_scoping_403(client, db_session):
    from app.models import Company, Customer, User
    from app.services.conversation_service import ConversationService

    other = Company(name="Другая", slug="other-company", is_active=True)
    db_session.add(other)
    db_session.flush()
    user = User(
        email="other@example.com",
        full_name="Другой менеджер",
        is_active=True,
        is_superuser=True,
        company_id=other.id,
    )
    db_session.add(user)
    customer = Customer(company_id=other.id, name="Чужой клиент")
    db_session.add(customer)
    db_session.flush()
    conversation = ConversationService(db_session).create_conversation(
        company_id=other.id, customer_id=customer.id
    )
    db_session.add(conversation)
    db_session.commit()

    # The seeded admin is scoped to the demo company, so another company's
    # conversation must be off-limits.
    resp = client.post(f"/api/v1/conversations/{conversation.id}/takeover")
    assert resp.status_code == 403


def test_takeover_audits_agent_action(client, db_session):
    conversation_id = _make_conversation(client, db_session)
    client.post(f"/api/v1/conversations/{conversation_id}/takeover")

    actions = client.get("/api/v1/actions").json()
    takeover = [
        a
        for a in actions
        if a["action_type"] == "conversation_takeover"
        and a["target_id"] == conversation_id
    ]
    assert len(takeover) == 1
    assert takeover[0]["risk_level"] == "LOW"


def test_conversation_list_includes_mode(client, db_session):
    conversation_id = _make_conversation(client, db_session)
    conversations = client.get("/api/v1/conversations").json()
    assert conversations[0]["mode"] == "ai_active"
    assert conversations[0]["id"] == conversation_id

    unknown = client.post(f"/api/v1/conversations/{uuid.uuid4()}/takeover")
    assert unknown.status_code == 404
