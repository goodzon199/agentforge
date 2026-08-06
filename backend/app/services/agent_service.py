from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Agent, AgentTool
from app.models.enums import AgentStatus, AgentType


class AgentService:
    """CRUD + provisioning of digital employees."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        company_id: uuid.UUID,
        name: str,
        role: str,
        slug: str,
        goal: str = "",
        description: str = "",
        instructions: str = "",
        agent_type: AgentType = AgentType.general,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        tool_names: list[str] | None = None,
    ) -> Agent:
        agent = Agent(
            company_id=company_id,
            name=name,
            role=role,
            slug=slug,
            goal=goal,
            description=description,
            instructions=instructions,
            type=agent_type,
            model=model,
            temperature=temperature,
            status=AgentStatus.idle,
            is_active=True,
            tools=[],
        )
        self.db.add(agent)
        self.db.flush()
        for tool_name in tool_names or []:
            self.db.add(
                AgentTool(agent_id=agent.id, tool_name=tool_name, enabled=True)
            )
        return agent

    def list(self, company_id: uuid.UUID | None = None) -> list[Agent]:
        stmt = select(Agent).order_by(Agent.created_at.desc())
        if company_id:
            stmt = stmt.where(Agent.company_id == company_id)
        return list(self.db.scalars(stmt).unique().all())

    def get(self, agent_id: uuid.UUID) -> Agent | None:
        return self.db.get(Agent, agent_id)

    def get_by_slug(self, slug: str) -> Agent | None:
        return self.db.scalars(select(Agent).where(Agent.slug == slug)).first()

    def update(self, agent: Agent, updates: dict[str, Any]) -> Agent:
        for key, value in updates.items():
            if hasattr(agent, key) and key not in ("id", "company_id"):
                setattr(agent, key, value)
        return agent

    def set_status(self, agent: Agent, status: AgentStatus) -> Agent:
        agent.status = status
        agent.is_active = status != AgentStatus.disabled
        return agent
