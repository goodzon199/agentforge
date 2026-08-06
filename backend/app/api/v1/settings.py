from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_agent_service
from app.core.config import settings
from app.core.database import get_db
from app.core.redis import redis_client
from app.llm.client import llm_client
from app.memory.service import MemoryService
from app.schemas.common import InfoResponse, MessageResponse
from app.schemas.settings import MemoryContextRead, MemoryWrite, ToolRead
from app.services.agent_service import AgentService
from app.tools.registry import tool_registry

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/info", response_model=InfoResponse)
def platform_info():
    return InfoResponse(
        name=settings.app_name,
        version="0.1.0",
        environment=settings.environment,
        llm_available=llm_client.available,
        redis_available=redis_client.available,
        generated_at=datetime.now(timezone.utc),
    )


@router.get("/tools", response_model=list[ToolRead])
def list_tools():
    return tool_registry.list()


@router.get("/agents/{agent_id}/memory", response_model=MemoryContextRead)
def agent_memory_context(
    agent_id: uuid.UUID,
    service: AgentService = Depends(get_agent_service),
    db: Session = Depends(get_db),
):
    agent = service.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    memory = MemoryService(db)
    return memory.build_context(agent)


@router.post("/agents/{agent_id}/memory", response_model=MemoryContextRead)
def write_agent_memory(
    agent_id: uuid.UUID,
    payload: MemoryWrite,
    service: AgentService = Depends(get_agent_service),
    db: Session = Depends(get_db),
):
    agent = service.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Агент не найден")
    memory = MemoryService(db)
    if payload.memory_type == "knowledge":
        memory.remember_knowledge(
            agent.company_id, title=payload.kind, content=payload.content, tags=payload.tags
        )
    elif payload.memory_type == "long":
        memory.remember_long(agent, payload.content, kind=payload.kind)
    else:
        memory.remember_short(agent, payload.content, kind=payload.kind)
    db.commit()
    return memory.build_context(agent)
