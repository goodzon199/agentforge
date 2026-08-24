"""Sprint 5.8.3 — Pack Context Contract (core side).

Covers the dispatch payload builder and the pull-based Context API with its
pack permission gate.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Conversation, ConversationMessage, Customer, Pack, Task
from app.orchestrator.orchestrator import Orchestrator


def _make_conversation(db):
    from app.models import Company

    company = db.scalars(select(Company)).first()
    customer = Customer(
        company_id=company.id,
        name="Тест Клиент",
        phone="+7 900 000-00-00",
        email="client@example.com",
    )
    db.add(customer)
    db.flush()
    conversation = Conversation(company_id=company.id, customer_id=customer.id)
    db.add(conversation)
    db.flush()
    message = ConversationMessage(
        conversation_id=conversation.id,
        content="Нужны тормозные колодки на BMW X5",
        sender_type="customer",
    )
    db.add(message)
    db.flush()
    return company, customer, conversation, message


def _make_task(db, conversation, message) -> Task:
    from app.models import Company

    company = db.scalars(select(Company)).first()
    task = Task(
        company_id=company.id,
        title="process message",
        objective="process_customer_message",
        input_data={
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
        },
    )
    db.add(task)
    db.flush()
    return task


def test_build_pack_context_ships_contract(db_session):
    _, _, conversation, message = _make_conversation(db_session)
    task = _make_task(db_session, conversation, message)

    context = Orchestrator()._build_pack_context(db_session, task)

    assert context["tenant"]["company_id"] == str(conversation.company_id)
    assert context["actor"]["customer_id"] == str(conversation.customer_id)
    assert context["conversation"]["id"] == str(conversation.id)
    assert context["conversation"]["channel"] == "web"
    assert context["message"]["id"] == str(message.id)
    assert "колодки" in context["message"]["text"]
    assert isinstance(context["context"]["recent_messages"], list)


def test_build_pack_context_empty_without_ids(db_session):
    task = Task(company_id=uuid.uuid4(), title="process message", objective="process_customer_message", input_data={})
    db_session.add(task)
    db_session.flush()

    context = Orchestrator()._build_pack_context(db_session, task)

    assert context == {}


def test_context_api_requires_pack_header(db_session, client):
    _, _, conversation, _ = _make_conversation(db_session)
    headers = {"X-Internal-Token": settings.internal_api_token}

    response = client.get(
        f"/internal/context/conversations/{conversation.id}", headers=headers
    )

    assert response.status_code == 403


def test_context_api_forbids_missing_permission(db_session, client):
    _, _, conversation, _ = _make_conversation(db_session)
    db_session.add(
        Pack(
            name="nopack",
            version="1.0.0",
            base_url="http://localhost:9",
            permissions=["conversation.write"],
            state="active",
            is_active=True,
        )
    )
    db_session.flush()
    headers = {
        "X-Internal-Token": settings.internal_api_token,
        "X-Pack-Name": "nopack",
    }

    response = client.get(
        f"/internal/context/conversations/{conversation.id}", headers=headers
    )

    assert response.status_code == 403


def test_context_api_returns_conversation_with_permission(db_session, client):
    _, customer, conversation, message = _make_conversation(db_session)
    db_session.add(
        Pack(
            name="readerpack",
            version="1.0.0",
            base_url="http://localhost:9",
            permissions=["conversation.read"],
            state="active",
            is_active=True,
        )
    )
    db_session.flush()
    headers = {
        "X-Internal-Token": settings.internal_api_token,
        "X-Pack-Name": "readerpack",
    }

    response = client.get(
        f"/internal/context/conversations/{conversation.id}", headers=headers
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation"]["id"] == str(conversation.id)
    assert payload["customer"]["id"] == str(customer.id)
    assert payload["messages"][0]["content"] == message.content


def test_context_api_customer_profile_gate(db_session, client):
    _, customer, _, _ = _make_conversation(db_session)
    db_session.add(
        Pack(
            name="custpack",
            version="1.0.0",
            base_url="http://localhost:9",
            permissions=["customer.read"],
            state="active",
            is_active=True,
        )
    )
    db_session.flush()
    headers = {
        "X-Internal-Token": settings.internal_api_token,
        "X-Pack-Name": "custpack",
    }

    ok = client.get(f"/internal/context/customers/{customer.id}", headers=headers)
    denied = client.get(
        f"/internal/context/customers/{customer.id}",
        headers={"X-Internal-Token": settings.internal_api_token},
    )

    assert ok.status_code == 200
    assert ok.json()["name"] == "Тест Клиент"
    assert denied.status_code == 403


def test_context_api_customer_forbidden_without_customer_read(db_session, client):
    """A pack with other permissions but no ``customer.read`` gets 403."""
    _, customer, _, _ = _make_conversation(db_session)
    db_session.add(
        Pack(
            name="noreadpack",
            version="1.0.0",
            base_url="http://localhost:9",
            permissions=["conversation.read", "supplier.search"],
            state="active",
            is_active=True,
        )
    )
    db_session.flush()
    headers = {
        "X-Internal-Token": settings.internal_api_token,
        "X-Pack-Name": "noreadpack",
    }

    response = client.get(
        f"/internal/context/customers/{customer.id}", headers=headers
    )

    assert response.status_code == 403


@pytest.fixture
def pack_service(db_session, monkeypatch):
    from app.services.pack_service import PackService

    # enable() probes the pack over HTTP; tests stub the health gate.
    monkeypatch.setattr(PackService, "_probe_health", lambda self, url: True)
    return PackService(db_session)


def _register(pack_service, name: str, agents: list[dict]):
    from shared.pack import parse_manifest

    manifest = parse_manifest(
        {
            "name": name,
            "version": "1.0.0",
            "display_name": name.title(),
            "base_url": "http://localhost:9",
            "required_core_version": ">=0.0.0",
            "permissions": ["customer.read"],
            "agents": agents,
        }
    )
    return pack_service.register("http://localhost:9", manifest)


def test_disable_deactivates_agent_projection(db_session, pack_service):
    from app.models import Agent

    _register(
        pack_service, "lifepack", [{"type": "intake", "display_name": "Intake"}]
    )
    pack_service.enable("lifepack")
    slug = "lifepack-intake-agent"
    agent = db_session.scalars(select(Agent).where(Agent.slug == slug)).first()
    assert agent is not None and agent.is_active

    pack_service.disable("lifepack")

    db_session.expire_all()
    agent = db_session.scalars(select(Agent).where(Agent.slug == slug)).first()
    assert not agent.is_active
    assert agent.status.value == "disabled"

    # Re-enable reactivates the projection instead of duplicating it.
    pack_service.enable("lifepack")
    db_session.expire_all()
    agents = db_session.scalars(select(Agent).where(Agent.slug == slug)).all()
    assert len(agents) == 1
    assert agents[0].is_active


def test_uninstall_deletes_agent_projection(db_session, pack_service):
    from app.models import Agent

    _register(
        pack_service, "gonepack", [{"type": "intake", "display_name": "Intake"}]
    )
    pack_service.enable("gonepack")
    assert (
        db_session.scalars(
            select(Agent).where(Agent.slug == "gonepack-intake-agent")
        ).first()
        is not None
    )

    pack_service.uninstall("gonepack")

    assert (
        db_session.scalars(
            select(Agent).where(Agent.slug == "gonepack-intake-agent")
        ).first()
        is None
    )


def test_sync_deactivates_types_removed_from_manifest(db_session, pack_service):
    from app.models import Agent

    _register(
        pack_service,
        "shrinkpack",
        [
            {"type": "intake", "display_name": "Intake"},
            {"type": "search", "display_name": "Search"},
        ],
    )
    pack_service.enable("shrinkpack")
    assert (
        db_session.scalars(
            select(Agent).where(Agent.slug == "shrinkpack-search-agent")
        ).first().is_active
    )

    pack = pack_service.get("shrinkpack")
    pack.agents = [{"type": "intake", "display_name": "Intake"}]
    pack_service._sync_pack_agents(pack)
    pack_service.db.commit()

    intake = db_session.scalars(
        select(Agent).where(Agent.slug == "shrinkpack-intake-agent")
    ).first()
    search = db_session.scalars(
        select(Agent).where(Agent.slug == "shrinkpack-search-agent")
    ).first()
    assert intake.is_active
    assert not search.is_active
