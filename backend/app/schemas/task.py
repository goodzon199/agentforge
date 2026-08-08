from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import TaskPriority, TaskStatus
from app.schemas.common import ORMModel


class TaskCreate(BaseModel):
    company_id: uuid.UUID
    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1)
    priority: TaskPriority = TaskPriority.normal
    input_data: dict[str, Any] = {}


class TaskRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID | None
    title: str
    objective: str
    status: TaskStatus
    priority: TaskPriority
    input_data: dict[str, Any]
    output_data: dict[str, Any] | None
    error: str | None
    routing_decision: dict[str, Any] | None
    retries: int
    replayed_from_task_id: uuid.UUID | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class TaskEventRead(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    agent_id: uuid.UUID | None
    source: str
    level: str
    message: str
    meta: dict[str, Any]
    created_at: datetime


class TaskDetail(TaskRead):
    events: list[TaskEventRead] = []


class DeadTaskRead(ORMModel):
    id: uuid.UUID
    task_id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID | None
    objective: str
    payload: dict[str, Any]
    exception_kind: str
    error: str | None
    attempts: int
    dead_at: datetime
    replayed_task_id: uuid.UUID | None
    created_at: datetime
