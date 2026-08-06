from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_task_service
from app.orchestrator.orchestrator import orchestrator
from app.schemas.task import TaskCreate, TaskDetail, TaskEventRead, TaskRead
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
    service: TaskService = Depends(get_task_service),
):
    return [_read(t) for t in service.list(company_id=company_id, status=status, limit=limit, offset=offset)]


@router.post("", response_model=TaskDetail, status_code=201)
def create_task(
    payload: TaskCreate,
    service: TaskService = Depends(get_task_service),
):
    task = service.create(**payload.model_dump())
    service.db.commit()
    service.db.refresh(task)
    task = orchestrator.submit(service.db, task)
    service.db.refresh(task)
    return _detail(task)


@router.get("/{task_id}", response_model=TaskDetail)
def get_task(
    task_id: uuid.UUID,
    service: TaskService = Depends(get_task_service),
):
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return _detail(task)


@router.get("/{task_id}/events", response_model=list[TaskEventRead])
def get_task_events(
    task_id: uuid.UUID,
    service: TaskService = Depends(get_task_service),
):
    if service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return [TaskEventRead.model_validate(e) for e in service.events(task_id)]


@router.post("/{task_id}/cancel", response_model=TaskRead)
def cancel_task(
    task_id: uuid.UUID,
    service: TaskService = Depends(get_task_service),
):
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    service.cancel(task)
    service.db.commit()
    service.db.refresh(task)
    return _read(task)
