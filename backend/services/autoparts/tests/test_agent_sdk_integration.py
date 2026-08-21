from __future__ import annotations

import uuid

from shared.agents import run_agent
from sqlalchemy import select

from app.agents.base import BaseAgent
from app.agents.context import AgentPermissions
from app.agents.registry import agent_registry
from app.models import Agent as AgentRecord
from app.models import AgentAction
from app.models.enums import AgentActionStatus
from app.tools.registry import tool_registry


def _task_id() -> uuid.UUID:
    return uuid.uuid4()


def _system_agent(db_session) -> BaseAgent:
    record = db_session.scalars(
        select(AgentRecord).where(AgentRecord.slug == "system-agent")
    ).first()
    from app.llm.client import llm_client
    from app.memory.service import MemoryService

    return agent_registry.get_class("system")(
        record=record,
        memory=MemoryService(db_session),
        tools=tool_registry,
        llm=llm_client,
        db=db_session,
    )


def test_registry_describes_agents():
    kinds = agent_registry.kinds()
    assert set(kinds) == {"system", "email", "search", "intake", "pricing", "sales"}
    info = agent_registry.get("system").describe()
    assert info["kind"] == "system"
    assert agent_registry.resolve_handoff("SearchAgent") == "search"


def test_build_context_wires_facades(db_session):
    agent = _system_agent(db_session)
    ctx = agent.build_context(
        "routing test", {"k": "v"}, task_id=_task_id(), company_id=ctx_company(db_session)
    )
    assert ctx.objective == "routing test"
    assert ctx.input_data == {"k": "v"}
    assert ctx.agent.id == agent.record.id
    assert ctx.llm is not None
    assert ctx.db is db_session
    assert ctx.memory is not None and ctx.tools is not None
    assert ctx.actions is not None and ctx.approvals is not None
    assert ctx.permissions is not None and ctx.trace is not None and ctx.events is not None
    assert agent.ctx is ctx


def ctx_company(db_session):
    from app.models import Company

    return db_session.scalars(select(Company)).first().id


def test_ctx_actions_records_auditable_row(db_session):
    agent = _system_agent(db_session)
    ctx = agent.build_context(
        "routing test", {}, task_id=_task_id(), company_id=ctx_company(db_session)
    )
    action = ctx.actions.record(
        "route_task",
        target_type="task",
        target_id="t-1",
        input_data={"objective": "routing test"},
        requires_approval=False,
    )
    db_session.flush()
    assert action.company_id == ctx_company(db_session)
    assert action.agent_id == agent.record.id
    assert action.status == AgentActionStatus.pending
    assert db_session.scalars(select(AgentAction)).first().id == action.id


def test_ctx_approvals_requests_pending_human_step(db_session):
    agent = _system_agent(db_session)
    ctx = agent.build_context(
        "routing test", {}, task_id=_task_id(), company_id=ctx_company(db_session)
    )
    action = ctx.approvals.request(
        message="Подтвердите передачу задачи.",
        target_type="task",
        target_id="t-1",
    )
    db_session.flush()
    assert action.requires_approval is True
    assert action.status == AgentActionStatus.pending
    assert action.action_type == "approval_request"


def test_ctx_permissions_gate_from_manifest(db_session):
    agent = _system_agent(db_session)
    ctx = agent.build_context(
        "routing test", {}, task_id=_task_id(), company_id=ctx_company(db_session)
    )
    allowed = ctx.permissions.allowed()
    assert isinstance(allowed, list)
    # manifest.yaml declares the pack permissions, so the gate must allow them.
    assert len(allowed) > 0


def test_run_agent_via_sdk_contract(db_session):
    agent = _system_agent(db_session)
    ctx = agent.build_context(
        "search_parts",
        {},
        task_id=_task_id(),
        company_id=ctx_company(db_session),
    )
    output = run_agent(agent, ctx)
    assert output.response
    assert output.routing_decision is not None


def test_agent_permissions_denies_unknown(db_session):
    gate = AgentPermissions(agent_record(db_session))
    try:
        gate.require("not.declared.anywhere")
    except PermissionError:
        pass
    else:
        raise AssertionError("expected PermissionError")


def agent_record(db_session):
    return db_session.scalars(
        select(AgentRecord).where(AgentRecord.slug == "system-agent")
    ).first()
