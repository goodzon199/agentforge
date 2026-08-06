from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.agent_service import AgentService
from app.services.company_service import CompanyService
from app.services.task_service import TaskService


def get_company_service(db: Session = Depends(get_db)) -> CompanyService:
    return CompanyService(db)


def get_agent_service(db: Session = Depends(get_db)) -> AgentService:
    return AgentService(db)


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    return TaskService(db)
