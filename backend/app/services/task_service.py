from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task, TaskEvent
from app.models.enums import TaskPriority, TaskStatus


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        company_id: uuid.UUID,
        title: str,
        objective: str,
        priority: TaskPriority = TaskPriority.normal,
        input_data: dict[str, Any] | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> Task:
        task = Task(
            company_id=company_id,
            agent_id=agent_id,
            title=title,
            objective=objective,
            status=TaskStatus.pending,
            priority=priority,
            input_data=input_data or {},
        )
        self.db.add(task)
        return task

    def list(
        self,
        company_id: uuid.UUID | None = None,
        status: TaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        stmt = select(Task).order_by(Task.created_at.desc())
        if company_id:
            stmt = stmt.where(Task.company_id == company_id)
        if status:
            stmt = stmt.where(Task.status == status)
        return list(self.db.scalars(stmt.offset(offset).limit(limit)).unique().all())

    def get(self, task_id: uuid.UUID) -> Task | None:
        return self.db.get(Task, task_id)

    def events(self, task_id: uuid.UUID) -> list[TaskEvent]:
        stmt = (
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.created_at.asc())
        )
        return list(self.db.scalars(stmt).unique().all())

    def cancel(self, task: Task) -> Task:
        if task.status in (TaskStatus.pending, TaskStatus.queued):
            task.status = TaskStatus.cancelled
        return task

    def update(self, task: Task, updates: dict[str, Any]) -> Task:
        for key, value in updates.items():
            if hasattr(task, key) and key not in ("id", "company_id"):
                setattr(task, key, value)
        return task
