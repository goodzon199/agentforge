from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_task_service
from app.core.database import get_db
from app.models import TaskEvent
from app.schemas.task import TaskEventRead
from app.services.task_service import TaskService

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=list[TaskEventRead])
def list_logs(
    level: str | None = None,
    source: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db),
    service: TaskService = Depends(get_task_service),
):
    stmt = select(TaskEvent).order_by(TaskEvent.created_at.desc()).offset(offset).limit(limit)
    if level:
        stmt = stmt.where(TaskEvent.level == level)
    if source:
        stmt = stmt.where(TaskEvent.source == source)
    events = list(db.scalars(stmt).unique().all())
    return [TaskEventRead.model_validate(e) for e in events]
