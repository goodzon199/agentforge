from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, Company
from app.models.enums import AgentStatus, AgentType
from app.orchestrator.orchestrator import SYSTEM_AGENT_SLUG

logger = logging.getLogger(__name__)

DEMO_COMPANY_SLUG = "demo"
DEMO_COMPANY_NAME = "Демо-компания"

SYSTEM_AGENT_GOAL = (
    "Оркестрировать задачи: получать запросы и направлять их профильным агентам."
)
SYSTEM_AGENT_INSTRUCTIONS = (
    "Ты — SystemAgent, диспетчер. Получаешь задачу, определяешь нужного "
    "специализированного агента и возвращаешь ответ вида: "
    "'Для выполнения этой задачи нужен <AgentName>'. Сейчас ты поддерживаешь "
    "маршрутизацию к SearchAgent (поиск) и EmailAgent (почта)."
)


def seed_demo(db: Session) -> dict[str, object]:
    """Create the demo company and the SystemAgent if they don't exist."""
    created = {"company": False, "system_agent": False}

    company = db.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    if company is None:
        company = Company(
            name=DEMO_COMPANY_NAME,
            slug=DEMO_COMPANY_SLUG,
            description="Компания по умолчанию для первого запуска платформы.",
            is_active=True,
            agent_quota=10,
        )
        db.add(company)
        db.flush()
        created["company"] = True
        logger.info("Создана демо-компания '%s'", DEMO_COMPANY_NAME)

    agent = db.scalars(
        select(Agent).where(Agent.slug == SYSTEM_AGENT_SLUG)
    ).first()
    if agent is None:
        agent = Agent(
            company_id=company.id,
            name="SystemAgent",
            role="Диспетчер и роутер задач",
            slug=SYSTEM_AGENT_SLUG,
            goal=SYSTEM_AGENT_GOAL,
            description=(
                "Первый агент платформы. Умеет получать задачу и определять, "
                "какой специализированный агент нужен для её выполнения."
            ),
            instructions=SYSTEM_AGENT_INSTRUCTIONS,
            type=AgentType.system,
            status=AgentStatus.idle,
            is_active=True,
            model="gpt-4o-mini",
            temperature=0.3,
            tools=[],
        )
        db.add(agent)
        created["system_agent"] = True
        logger.info("Создан SystemAgent")

    db.commit()
    return created
