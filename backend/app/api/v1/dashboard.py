from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Agent, Company, Task, TaskEvent

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
def dashboard_stats(db: Session = Depends(get_db)):
    return DashboardStats(
        companies=db.scalar(select(func.count()).select_from(Company)) or 0,
        agents=db.scalar(select(func.count()).select_from(Agent)) or 0,
        tasks=db.scalar(select(func.count()).select_from(Task)) or 0,
        tasks_completed=db.scalar(
            select(func.count()).select_from(Task).where(Task.status == "completed")
        )
        or 0,
        tasks_failed=db.scalar(
            select(func.count()).select_from(Task).where(Task.status == "failed")
        )
        or 0,
        agents_active=db.scalar(
            select(func.count()).select_from(Agent).where(Agent.is_active.is_(True))
        )
        or 0,
        logs_total=db.scalar(select(func.count()).select_from(TaskEvent)) or 0,
    )
