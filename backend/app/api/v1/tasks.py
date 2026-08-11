from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.access import company_scope, ensure_company
from app.api.deps import get_current_user, get_task_service
from app.models import DeadTask, User
from app.orchestrator.orchestrator import orchestrator
from app.schemas.task import (
    DeadTaskRead,
    TaskCreate,
    TaskDetail,
    TaskEventRead,
    TaskRead,
)
from app.services.task_service import TaskService

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _read(task) -> TaskRead:
    return TaskRead.model_validate(task)


def _detail(task) -> TaskDetail:
    return TaskDetail(
        **_read(task).model_dump(),
        events=[TaskEventRead.model_validate(e) for e in task.events],
    )


@router.get("", response_model=list[TaskRead])
def list_tasks(
    company_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
):
    scope = company_scope(user)
    if scope is not None:
        company_id = scope
    return [_read(t) for t in service.list(company_id=company_id, status=status, limit=limit, offset=offset)]


@router.post("", response_model=TaskDetail, status_code=201)
def create_task(
    payload: TaskCreate,
    user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
):
    ensure_company(user, payload.company_id)
    task = service.create(**payload.model_dump())
    service.db.commit()
    service.db.refresh(task)
    task = orchestrator.submit(service.db, task)
    service.db.refresh(task)
    return _detail(task)


@router.get("/dead", response_model=list[DeadTaskRead])
def list_dead_tasks(
    limit: int = 100,
    user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
):
    """Dead-letter queue: tasks that exhausted retries (source of truth)."""
    stmt = (
        select(DeadTask).order_by(DeadTask.dead_at.desc()).limit(min(limit, 500))
    )
    scope = company_scope(user)
    if scope is not None:
        stmt = stmt.where(DeadTask.company_id == scope)
    return [DeadTaskRead.model_validate(d) for d in service.db.scalars(stmt).unique().all()]


@router.post("/{task_id}/replay", response_model=TaskDetail)
def replay_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
):
    """Replay a terminal task: creates a NEW task from it (sprint 3.5)."""
    original = service.get(task_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    ensure_company(user, original.company_id)
    try:
        task = service.replay(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    task = orchestrator.submit(service.db, task)
    service.db.refresh(task)
    return _detail(task)


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
):
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    ensure_company(user, task.company_id)
    return _detail(task)


@router.get("/{task_id}/events", response_model=list[TaskEventRead])
def get_task_events(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
):
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    ensure_company(user, task.company_id)
    return [TaskEventRead.model_validate(e) for e in service.events(task_id)]


@router.post("/{task_id}/cancel", response_model=TaskRead)
def cancel_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: TaskService = Depends(get_task_service),
):
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    ensure_company(user, task.company_id)
    service.cancel(task)
    service.db.commit()
    service.db.refresh(task)
    return _read(task)
