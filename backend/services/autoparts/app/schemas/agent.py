from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AgentStatus, AgentType
from app.schemas.common import ORMModel


class AgentToolConfig(BaseModel):
    tool_name: str
    enabled: bool = True
    config: dict = {}


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9-]+$")
    goal: str = ""
    description: str = ""
    instructions: str = ""
    type: AgentType = AgentType.general
    model: str = "gpt-4o-mini"
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    tool_names: list[str] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    goal: str | None = None
    description: str | None = None
    instructions: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    status: AgentStatus | None = None
    tool_names: list[str] | None = None


class AgentRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    role: str
    slug: str
    goal: str
    description: str
    instructions: str
    type: AgentType
    model: str
    temperature: float
    status: AgentStatus
    is_active: bool
    tasks_total: int
    tasks_completed: int
    tasks_failed: int
    avg_success_rate: float
    total_llm_calls: int
    tools: list[AgentToolConfig]
    created_at: datetime
    updated_at: datetime


class AgentStatusUpdate(BaseModel):
    status: AgentStatus
