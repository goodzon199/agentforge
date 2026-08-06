from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Agent, AgentTool, Company
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

EMAIL_AGENT_GOAL = (
    "Отправлять письма клиентам и контрагентам по поручению SystemAgent."
)
EMAIL_AGENT_INSTRUCTIONS = (
    "Ты — EmailAgent. Получаешь задачу от SystemAgent, извлекаешь получателя "
    "(to), тему (subject) и текст письма (body) и отправляешь их через "
    "инструмент email. Если получатель не указан — используй адрес по умолчанию."
)


def _ensure_agent(
    db: Session,
    *,
    slug: str,
    name: str,
    role: str,
    goal: str,
    description: str,
    instructions: str,
    agent_type: AgentType,
    company_id,
    tool_names: list[str] | None = None,
) -> bool:
    agent = db.scalars(select(Agent).where(Agent.slug == slug)).first()
    if agent is not None:
        return False
    agent = Agent(
        company_id=company_id,
        name=name,
        role=role,
        slug=slug,
        goal=goal,
        description=description,
        instructions=instructions,
        type=agent_type,
        status=AgentStatus.idle,
        is_active=True,
        model=settings.default_agent_model,
        temperature=settings.default_agent_temperature,
        tools=[],
    )
    db.add(agent)
    db.flush()
    for tool_name in tool_names or []:
        db.add(AgentTool(agent_id=agent.id, tool_name=tool_name, enabled=True))
    logger.info("Создан агент %s", name)
    return True


def seed_demo(db: Session) -> dict[str, object]:
    """Create the demo company and the built-in agents if they don't exist."""
    created = {"company": False, "system_agent": False, "email_agent": False}

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

    created["system_agent"] = _ensure_agent(
        db,
        slug=SYSTEM_AGENT_SLUG,
        name="SystemAgent",
        role="Диспетчер и роутер задач",
        goal=SYSTEM_AGENT_GOAL,
        description=(
            "Первый агент платформы. Получает задачу и определяет, какой "
            "специализированный агент нужен для её выполнения."
        ),
        instructions=SYSTEM_AGENT_INSTRUCTIONS,
        agent_type=AgentType.system,
        company_id=company.id,
    )

    created["email_agent"] = _ensure_agent(
        db,
        slug="email-agent",
        name="EmailAgent",
        role="Отправка электронных писем",
        goal=EMAIL_AGENT_GOAL,
        description=(
            "Специализированный агент: превращает задачу в письмо и отправляет "
            "его через SMTP (в демо-стеке — MailHog)."
        ),
        instructions=EMAIL_AGENT_INSTRUCTIONS,
        agent_type=AgentType.specialized,
        company_id=company.id,
        tool_names=["email"],
    )

    db.commit()
    return created
