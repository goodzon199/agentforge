"""Sprint 5.8.3 — Pack Context Contract (pack side).

Core ships tenant/actor/conversation/message with the dispatch; the intake
agent must process the message without SELECTing core-owned storage and the
pack must anchor its domain rows to core ids idempotently.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from shared.internal import internal_token


def _client(db_session) -> TestClient:
    """TestClient without entering its context manager: the app lifespan
    opens real connections (redis/db); dependency overrides are enough here,
    mirroring conftest.client."""
    from app.core.database import get_db
    from app.core.redis import redis_client
    from app.main import app

    saved_enabled = redis_client._enabled
    redis_client._enabled = False

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _context(message_text: str) -> dict:
    return {
        "tenant": {"company_id": str(uuid.uuid4())},
        "actor": {"customer_id": str(uuid.uuid4())},
        "conversation": {"id": str(uuid.uuid4()), "channel": "web"},
        "message": {"id": str(uuid.uuid4()), "text": message_text},
        "history": [],
    }


def _execute(client: TestClient, context: dict, dispatch_id: str | None = None):
    return client.post(
        "/internal/agents/execute",
        headers={"X-Internal-Token": internal_token()},
        json={
            "agent_type": "intake",
            "objective": "process_customer_message",
            "dispatch_id": dispatch_id or str(uuid.uuid4()),
            "context": context,
        },
    )


def test_contract_dispatch_creates_anchored_part_request(db_session):
    from app.models import Conversation, DomainThreadLink, PartRequest

    client = _client(db_session)
    context = _context("Нужны тормозные колодки на BMW X5 2018")

    response = _execute(client, context)

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["action"] in {"part_request_created", "clarification"}

    message_id = uuid.UUID(context["message"]["id"])
    conversation_id = uuid.UUID(context["conversation"]["id"])
    customer_id = uuid.UUID(context["actor"]["customer_id"])

    part_request = db_session.scalars(
        select(PartRequest).where(PartRequest.core_message_id == message_id)
    ).first()
    assert part_request is not None
    assert part_request.core_conversation_id == conversation_id
    assert part_request.core_customer_id == customer_id

    link = db_session.get(DomainThreadLink, conversation_id)
    assert link is not None
    assert link.core_customer_id == customer_id

    # Local anchors exist so pack-side FKs keep working without core reads.
    local_conversation = db_session.get(Conversation, link.conversation_id)
    assert local_conversation is not None


def test_duplicate_message_delivery_is_idempotent(db_session):
    from app.models import PartRequest

    client = _client(db_session)
    context = _context("Нужны тормозные колодки на BMW X5 2018")
    dispatch_id = str(uuid.uuid4())

    first = _execute(client, context, dispatch_id=dispatch_id)
    second = _execute(client, context, dispatch_id=dispatch_id)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["action"] == "already_processed"
    count = db_session.scalar(
        select(func.count())
        .select_from(PartRequest)
        .where(PartRequest.core_message_id == uuid.UUID(context["message"]["id"]))
    )
    assert count == 1


def test_dispatch_without_context_falls_back_to_legacy_path(db_session):
    client = _client(db_session)

    response = client.post(
        "/internal/agents/execute",
        headers={"X-Internal-Token": internal_token()},
        json={
            "agent_type": "intake",
            "objective": "process_customer_message",
            "input_data": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["action"] == "error"
