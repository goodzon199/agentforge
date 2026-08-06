from __future__ import annotations

from sqlalchemy import select

from app.agents.system import SystemAgent
from app.core.seeding import SYSTEM_AGENT_SLUG
from app.llm.client import LLMClient
from app.memory.service import MemoryService
from app.models import Agent
from app.tools.registry import ToolRegistry


def _make_agent(db_session) -> SystemAgent:
    record = db_session.scalars(
        select(Agent).where(Agent.slug == SYSTEM_AGENT_SLUG)
    ).first()
    return SystemAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=ToolRegistry(),
        llm=LLMClient(),
    )


def test_system_agent_routes_brake_pads_to_search(db_session):
    agent = _make_agent(db_session)
    output = agent.execute("Найди тормозные колодки", {})
    assert output.handoff_agent == "SearchAgent"
    assert "SearchAgent" in output.response
    assert output.routing_decision["engine"] == "rules"


def test_system_agent_routes_email(db_session):
    agent = _make_agent(db_session)
    output = agent.execute("Отправь письмо клиенту", {})
    assert output.handoff_agent == "EmailAgent"


def test_system_agent_generic_task_no_handoff(db_session):
    agent = _make_agent(db_session)
    output = agent.execute("Подготовь отчёт по продажам", {})
    assert output.handoff_agent is None


def test_system_agent_writes_short_memory(db_session):
    from sqlalchemy import select

    from app.models import ShortMemory

    agent = _make_agent(db_session)
    output = agent.execute("Найди тормозные колодки", {})
    agent.remember(output.response, kind="task_result")
    db_session.commit()
    entries = db_session.scalars(select(ShortMemory)).all()
    assert len(entries) >= 1
