from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Task, TaskEvent
from app.models.enums import TaskPriority, TaskStatus
from app.services.audit_service import AuditService


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
            .with_for_update()
        )
        tasks = list(self.db.scalars(stmt).unique().all())
        for task in tasks:
            # Idempotency guard: several worker threads sweep on the same
            # wall-clock tick; the first one to lock the row flips it to failed
            # and later sweepers see it already timed out.
            if task.error and task.error.startswith("task_timeout"):
                continue
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
            # Sessions run with autoflush=False; make the failed status visible
            # to maybe_finish_trace's count queries before closing the trace.
            self.db.flush()
            from app.tracing.tracer import maybe_finish_trace

            for task in tasks:
                maybe_finish_trace(self.db, task.trace_id)
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
        trace_id: uuid.UUID | None = None,
    ) -> Task:
        if trace_id is None:
            from app.tracing.tracer import current_trace_id

            trace_id = current_trace_id()
        task = Task(
            company_id=company_id,
            agent_id=agent_id,
            title=title,
            objective=objective,
            status=TaskStatus.pending,
            priority=priority,
            input_data=input_data or {},
            trace_id=trace_id,
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

    def replay_depth(self, task: Task) -> int:
        """How many generations of Replay produced this task (1 = direct replay)."""
        depth = 0
        seen: set[uuid.UUID] = set()
        current: Task | None = task
        while current is not None and current.replayed_from_task_id is not None:
            if current.id in seen:
                return depth  # loop guard — never trust a corrupt chain
            seen.add(current.id)
            depth += 1
            current = self.db.get(Task, current.replayed_from_task_id)
        return depth

    def replay(self, task_id: uuid.UUID) -> Task:
        """Create a NEW task from a terminal one (sprint 3.5 Replay).

        The original task's history (events, output, error) is never touched.
        The new task carries ``replayed_from_task_id`` so operators see the
        chain; a depth guard prevents infinite replay loops.
        """
        from app.core.config import settings

        original = self.get(task_id)
        if original is None:
            raise ValueError("Задача не найдена.")
        if original.status in (
            TaskStatus.pending,
            TaskStatus.queued,
            TaskStatus.running,
            TaskStatus.awaiting_routing,
        ):
            raise ValueError(
                "Повторить можно только завершённую задачу "
                f"(статус {original.status.value})."
            )
        if self.replay_depth(original) >= settings.task_max_replay_depth:
            raise ValueError(
                f"Превышена максимальная глубина повторов "
                f"({settings.task_max_replay_depth})."
            )

        task = Task(
            company_id=original.company_id,
            agent_id=original.agent_id,
            title=f"Повтор: {original.title}"[:240],
            objective=original.objective,
            status=TaskStatus.pending,
            priority=original.priority,
            input_data=dict(original.input_data or {}),
            replayed_from_task_id=original.id,
            trace_id=original.trace_id,
        )
        self.db.add(task)
        self.db.flush()  # assign task.id before the event references it
        self.db.add(
            TaskEvent(
                task_id=task.id,
                source="orchestrator",
                level="info",
                message=f"Повторно запущено из задачи {original.id}.",
                meta={"replayed_from_task_id": str(original.id)},
            )
        )
        # Link the dead-letter record (if any) so the DLQ shows the delivery.
        from app.models import DeadTask

        dead = self.db.scalar(
            select(DeadTask).where(DeadTask.task_id == original.id)
        )
        if dead is not None and dead.replayed_task_id is None:
            dead.replayed_task_id = task.id

        AuditService(self.db).record(
            action="task.replay",
            entity_type="task",
            entity_id=str(task.id),
            company_id=task.company_id,
            detail={
                "replayed_from_task_id": str(original.id),
                "title": task.title,
            },
        )
        self.db.commit()
        self.db.refresh(task)
        return task
