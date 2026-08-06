from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_agent_service, get_company_service
from app.models import Agent
from app.schemas.agent import AgentCreate, AgentRead, AgentStatusUpdate, AgentUpdate
from app.services.agent_service import AgentService
from app.services.company_service import CompanyService

router = APIRouter(prefix="/agents", tags=["agents"])


def _read(agent: Agent) -> AgentRead:
    return AgentRead(
        id=agent.id,
        company_id=agent.company_id,
        name=agent.name,
        role=agent.role,
        slug=agent.slug,
        goal=agent.goal,
        description=agent.description,
        instructions=agent.instructions,
        type=agent.type,
        model=agent.model,
        temperature=agent.temperature,
        status=agent.status,
        is_active=agent.is_active,
        tasks_total=agent.tasks_total,
        tasks_completed=agent.tasks_completed,
        tasks_failed=agent.tasks_failed,
        avg_success_rate=agent.avg_success_rate,
        total_llm_calls=agent.total_llm_calls,
        tools=[{"tool_name": t.tool_name, "enabled": t.enabled, "config": t.config} for t in agent.tools],
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _require_company(company_id: uuid.UUID, service: CompanyService) -> None:
    if service.get(company_id) is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")


@router.get("", response_model=list[AgentRead])
def list_agents(
    company_id: uuid.UUID | None = None,
    service: AgentService = Depends(get_agent_service),
):
    return [_read(a) for a in service.list(company_id)]


@router.post("", response_model=AgentRead, status_code=201)
def create_agent(
    payload: AgentCreate,
    service: AgentService = Depends(get_agent_service),
    company_service: CompanyService = Depends(get_company_service),
):
    _require_company(payload.company_id, company_service)
    if service.get_by_slug(payload.slug):
        raise HTTPException(status_code=409, detail="Агент с таким slug уже существует")
    data = payload.model_dump(exclude={"tool_names"})
    agent = service.create(**data, tool_names=payload.tool_names)
    service.db.commit()
    service.db.refresh(agent)
    return _read(agent)


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: uuid.UUID,
    service: AgentService = Depends(get_agent_service),
):
    agent = service.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    return _read(agent)


@router.patch("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    service: AgentService = Depends(get_agent_service),
):
    agent = service.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    data = payload.model_dump(exclude_unset=True)
    tool_names = data.pop("tool_names", None)
    if tool_names is not None:
        service.db.flush()
        agent.tools = [_new_tool(agent.id, t) for t in tool_names]
    service.update(agent, data)
    service.db.commit()
    service.db.refresh(agent)
    return _read(agent)


def _new_tool(agent_id: uuid.UUID, tool_name: str):
    from app.models import AgentTool

    return AgentTool(agent_id=agent_id, tool_name=tool_name, enabled=True)


@router.patch("/{agent_id}/status", response_model=AgentRead)
def set_agent_status(
    agent_id: uuid.UUID,
    payload: AgentStatusUpdate,
    service: AgentService = Depends(get_agent_service),
):
    agent = service.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    service.set_status(agent, payload.status)
    service.db.commit()
    service.db.refresh(agent)
    return _read(agent)


@router.delete("/{agent_id}", status_code=204)
def delete_agent(
    agent_id: uuid.UUID,
    service: AgentService = Depends(get_agent_service),
):
    agent = service.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    service.db.delete(agent)
    service.db.commit()
