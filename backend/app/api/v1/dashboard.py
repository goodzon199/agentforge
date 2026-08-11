from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.access import company_scope
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Agent, Company, Task, TaskEvent, User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class DashboardStats(BaseModel):
    companies: int
    agents: int
    tasks: int
    tasks_completed: int
    tasks_failed: int
    agents_active: int
    logs_total: int


@router.get("", response_model=DashboardStats)
def dashboard_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scope = company_scope(user)

    def _scoped(model, extra=None):
        stmt = select(func.count()).select_from(model)
        if scope is not None and hasattr(model, "company_id"):
            stmt = stmt.where(model.company_id == scope)
        if extra is not None:
            stmt = stmt.where(extra)
        return db.scalar(stmt) or 0

    return DashboardStats(
        companies=_scoped(Company),
        agents=_scoped(Agent),
        tasks=_scoped(Task),
        tasks_completed=_scoped(Task, Task.status == "completed"),
        tasks_failed=_scoped(Task, Task.status == "failed"),
        agents_active=_scoped(Agent, Agent.is_active.is_(True)),
        logs_total=db.scalar(
            select(func.count()).select_from(TaskEvent)
            .join(Task, TaskEvent.task_id == Task.id)
            .where(Task.company_id == scope)
        )
        or 0
        if scope is not None
        else (db.scalar(select(func.count()).select_from(TaskEvent)) or 0),
    )
