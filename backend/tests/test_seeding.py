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
