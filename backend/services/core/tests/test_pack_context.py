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


def _seed_workload_fixtures(
    db,
    monkeypatch=None,
    *,
    pack_name="readerpack",
    permissions=("conversation.read", "customer.read"),
):
    """Pack + identity + grants + a scoped conversation, ready for tokens."""
    from app.core.workload import OPERATION_PERMISSIONS
    from app.models import Company
    from app.services.pack_identity_service import PackIdentityService
    from app.services.pack_permission_service import PackPermissionService

    if monkeypatch is not None:
        monkeypatch.setitem(
            OPERATION_PERMISSIONS,
            f"dispatch.{pack_name}.intake",
            frozenset(permissions),
        )
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

    db.add(
        Pack(
            name=pack_name,
            version="1.0.0",
            base_url="http://localhost:9",
            permissions=list(permissions),
            state="active",
            is_active=True,
            agents=[{"type": "intake"}],
        )
    )
    db.flush()
    PackIdentityService(db).ensure(pack_name)
    svc = PackPermissionService(db)
    svc.sync_declared(pack_name, list(permissions), "1.0.0")
    for perm in permissions:
        svc.grant(pack_name, perm, actor_id=None)
    db.commit()
    return company, customer, conversation, message


def _workload_headers(
    db,
    *,
    pack_name="readerpack",
    company,
    conversation,
    customer,
    message,
    operation=None,
    extra_permissions=(),
    scope=None,
):
    from app.core.workload import WorkloadScope
    from app.services.workload_token_service import WorkloadTokenService

    operation = operation or f"dispatch.{pack_name}.intake"
    if scope is None:
        scope = WorkloadScope(
            conversation_ids=frozenset({str(conversation.id)}),
            customer_ids=frozenset({str(customer.id)}),
            message_ids=frozenset({str(message.id)}),
        )
    svc = WorkloadTokenService(db)
    token, claims = svc.issue(
        pack_id=pack_name,
        tenant_id=str(company.id),
        task_id=str(uuid.uuid4()),
        dispatch_id=str(uuid.uuid4()),
        operation=operation,
        scope=scope,
    )
    svc.record_dispatch(
        dispatch_id=claims["dispatch_id"],
        pack_id=pack_name,
        operation=operation,
        jti=claims["jti"],
        company_id=str(company.id),
    )
    db.commit()
    return {
        "X-Internal-Token": settings.internal_api_token,
        "Authorization": f"Bearer {token}",
    }


def test_context_api_requires_workload_bearer(db_session, client, monkeypatch):
    _, _, conversation, _, = _seed_workload_fixtures(db_session, monkeypatch)
    response = client.get(
        f"/internal/context/conversations/{conversation.id}",
        headers={"X-Internal-Token": settings.internal_api_token},
    )
    assert response.status_code == 401


def test_context_api_rejects_service_jwt_on_context(db_session, client, monkeypatch):
    """Invariant I1: a service token never opens Context API."""
    from app.models import Pack as PackModel
    from app.services.pack_identity_service import PackIdentityService

    company, customer, conversation, message = _seed_workload_fixtures(db_session, monkeypatch)
    identity = PackIdentityService(db_session).get("readerpack")
    token, _ = PackIdentityService(db_session).issue_service_token(identity)
    db_session.commit()
    assert PackModel is not None

    response = client.get(
        f"/internal/context/conversations/{conversation.id}",
        headers={
            "X-Internal-Token": settings.internal_api_token,
            "Authorization": f"Bearer {token}",
        },
    )
    assert response.status_code == 401


def test_context_api_returns_conversation_with_permission(db_session, client, monkeypatch):
    _, customer, conversation, message = _seed_workload_fixtures(db_session, monkeypatch)
    headers = _workload_headers(
        db_session,
        company=_first_company(db_session),
        conversation=conversation,
        customer=customer,
        message=message,
    )

    response = client.get(
        f"/internal/context/conversations/{conversation.id}", headers=headers
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation"]["id"] == str(conversation.id)
    assert payload["customer"]["id"] == str(customer.id)
    assert payload["messages"][0]["content"] == message.content


def _first_company(db):
    from app.models import Company

    return db.scalars(select(Company)).first()


def test_context_api_customer_profile_gate(db_session, client, monkeypatch):
    _, customer, conversation, message = _seed_workload_fixtures(db_session, monkeypatch)
    headers = _workload_headers(
        db_session,
        company=_first_company(db_session),
        conversation=conversation,
        customer=customer,
        message=message,
    )

    ok = client.get(f"/internal/context/customers/{customer.id}", headers=headers)
    denied = client.get(
        f"/internal/context/customers/{customer.id}",
        headers={"X-Internal-Token": settings.internal_api_token},
    )

    assert ok.status_code == 200
    assert ok.json()["name"] == "Тест Клиент"
    assert denied.status_code == 401


def test_context_api_forbidden_without_customer_read_claim(db_session, client, monkeypatch):
    """conversation.read-only token cannot pull customer profiles (W4)."""
    _, customer, conversation, message = _seed_workload_fixtures(
        db_session,
        monkeypatch,
        pack_name="convonly",
        permissions=["conversation.read"],
    )
    # Re-issue with only the conversation in scope (customer.read absent).
    headers = _workload_headers(
        db_session,
        pack_name="convonly",
        company=_first_company(db_session),
        conversation=conversation,
        customer=customer,
        message=message,
    )

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
