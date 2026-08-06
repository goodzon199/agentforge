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


def test_email_agent_sends_through_stubbed_tool(db_session):
    from sqlalchemy import select

    from app.agents.email import EmailAgent
    from app.tools.base import ToolResult

    record = db_session.scalars(
        select(Agent).where(Agent.slug == "email-agent")
    ).first()

    class _FakeTools:
        def run(self, name, **kwargs):
            assert name == "email"
            assert kwargs["to"] == "client@example.com"
            assert kwargs["subject"] == "Тест"
            assert "текст письма" in kwargs["body"]
            return ToolResult(
                ok=True,
                data={
                    "to": "client@example.com",
                    "subject": "Тест",
                    "from": "agentforge@agentos.local",
                    "transport": "mailhog:1025",
                },
            )

    agent = EmailAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=_FakeTools(),
        llm=LLMClient(),
    )
    output = agent.execute(
        "Напиши письмо",
        {"to": "client@example.com", "subject": "Тест", "body": "текст письма"},
    )
    assert output.data["action"] == "email_sent"
    assert output.data["to"] == "client@example.com"
    assert "Письмо отправлено" in output.response


def test_email_agent_falls_back_to_default_recipient(db_session):
    from sqlalchemy import select

    from app.agents.email import EmailAgent
    from app.core.config import settings
    from app.tools.base import ToolResult

    record = db_session.scalars(
        select(Agent).where(Agent.slug == "email-agent")
    ).first()

    class _FakeTools:
        def run(self, name, **kwargs):
            return ToolResult(
                ok=True,
                data={
                    "to": settings.email_default_to,
                    "subject": kwargs["subject"],
                    "from": settings.smtp_from,
                    "transport": "mailhog:1025",
                },
            )

    agent = EmailAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=_FakeTools(),
        llm=LLMClient(),
    )
    output = agent.execute("Отправь письмо о встрече", {})
    assert output.data["to"] == settings.email_default_to
    assert "встрече" in output.data["subject"]
