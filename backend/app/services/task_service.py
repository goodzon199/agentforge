from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task, TaskEvent
from app.models.enums import TaskPriority, TaskStatus


class TaskService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def mark_stale_tasks(
        self,
        *,
        max_seconds: float | None = None,
        now: datetime | None = None,
    ) -> int:
        """Watchdog: fail tasks stuck in a running state for too long.

        A task may hang (dead worker, stuck supplier). This sweeps it to
        ``failed`` so nothing waits forever and the dashboard can show the
        task-timeout rate. Returns how many tasks were failed.
        """
        from app.core.config import settings

        limit = max_seconds if max_seconds is not None else settings.task_max_running_seconds
        threshold = (now or datetime.now(timezone.utc)) - timedelta(seconds=limit)

        stmt = (
            select(Task)
            .where(Task.status.in_([TaskStatus.queued, TaskStatus.running]))
            .where(Task.started_at.isnot(None))
            .where(Task.started_at < threshold)
        )
        tasks = list(self.db.scalars(stmt).unique().all())
        for task in tasks:
            task.status = TaskStatus.failed
            task.error = f"task_timeout: превышен лимит {limit:.0f}с на выполнение"
            task.completed_at = datetime.now(timezone.utc)
            self.db.add(
                TaskEvent(
                    task_id=task.id,
                    source="orchestrator",
                    level="error",
                    message=task.error,
                    meta={"reason": "task_timeout", "max_seconds": limit},
                )
            )
        if tasks:
            self.db.commit()
        return len(tasks)

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
