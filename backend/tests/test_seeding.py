from __future__ import annotations

from sqlalchemy import select

from app.core.seeding import DEMO_COMPANY_SLUG, SYSTEM_AGENT_SLUG
from app.models import Agent, Company


def test_seed_creates_company_and_system_agent(db_session):
    company = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    assert company is not None

    agent = db_session.scalars(
        select(Agent).where(Agent.slug == SYSTEM_AGENT_SLUG)
    ).first()
    assert agent is not None
    assert agent.name == "SystemAgent"
    assert agent.company_id == company.id


def test_seed_creates_email_agent_with_tool(db_session):
    from app.models import AgentTool

    agent = db_session.scalars(
        select(Agent).where(Agent.slug == "email-agent")
    ).first()
    assert agent is not None
    assert agent.name == "EmailAgent"
    assert agent.type.value == "specialized"

    tool = db_session.scalars(
        select(AgentTool).where(AgentTool.agent_id == agent.id)
    ).first()
    assert tool is not None
    assert tool.tool_name == "email"


def test_seed_creates_search_agent_and_knowledge(db_session):
    from app.models import AgentTool, KnowledgeEntry

    agent = db_session.scalars(
        select(Agent).where(Agent.slug == "search-agent")
    ).first()
    assert agent is not None
    assert agent.name == "SearchAgent"

    tool = db_session.scalars(
        select(AgentTool).where(AgentTool.agent_id == agent.id)
    ).first()
    assert tool is not None
    assert tool.tool_name == "search"

    entries = db_session.scalars(select(KnowledgeEntry)).all()
    assert len(entries) == 3
    assert any("Тормозные" in e.title for e in entries)
