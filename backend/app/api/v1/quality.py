from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.access import company_scope
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import PromptVersion, User
from app.services.agent_quality_service import AgentQualityService
from app.services.prompt_service import PromptService

router = APIRouter(tags=["quality"])


# --- Agent quality ---------------------------------------------------------


class FeedbackRates(BaseModel):
    feedback_total: int
    acceptance: int
    edit: int
    rejection: int
    hallucination: int
    acceptance_rate: float | None = None
    edit_rate: float | None = None
    rejection_rate: float | None = None
    hallucination_rate: float | None = None


class AgentQualityRead(BaseModel):
    agent_id: str
    name: str
    slug: str
    role: str
    tasks_total: int
    tasks_completed: int
    tasks_failed: int
    success_rate: float | None = None
    avg_response_seconds: float | None = None
    feedback: FeedbackRates
    human_takeover: float | None = None
    llm_calls: int
    total_llm_cost: float
    cost_per_task: float | None = None


class PromptVersionQualityRead(FeedbackRates):
    agent_kind: str
    prompt_version: str


class AgentQualityReport(BaseModel):
    days: int
    agents: list[AgentQualityRead]
    by_prompt_version: list[PromptVersionQualityRead]


@router.get("/agents/quality", response_model=AgentQualityReport)
def agent_quality(
    days: int = 7,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = AgentQualityService(db).quality(company_id=company_scope(user), days=days)
    report = {
        "days": data["days"],
        "agents": [
            {
                **{k: a[k] for k in ("agent_id", "name", "slug", "role")},
                "tasks_total": a["tasks_total"],
                "tasks_completed": a["tasks_completed"],
                "tasks_failed": a["tasks_failed"],
                "success_rate": a["success_rate"],
                "avg_response_seconds": a["avg_response_seconds"],
                "feedback": FeedbackRates(
                    feedback_total=a["feedback_total"],
                    acceptance=a["acceptance"],
                    edit=a["edit"],
                    rejection=a["rejection"],
                    hallucination=a["hallucination"],
                    acceptance_rate=a["acceptance_rate"],
                    edit_rate=a["edit_rate"],
                    rejection_rate=a["rejection_rate"],
                    hallucination_rate=a["hallucination_rate"],
                ),
                "human_takeover": a["human_takeover"],
                "llm_calls": a["llm_calls"],
                "total_llm_cost": a["total_llm_cost"],
                "cost_per_task": a["cost_per_task"],
            }
            for a in data["agents"]
        ],
        "by_prompt_version": [
            PromptVersionQualityRead(
                agent_kind=r["agent_kind"],
                prompt_version=r["prompt_version"],
                feedback_total=r["feedback_total"],
                acceptance=r["acceptance"],
                edit=r["edit"],
                rejection=r["rejection"],
                hallucination=r["hallucination"],
                acceptance_rate=r["acceptance_rate"],
                edit_rate=r["edit_rate"],
                rejection_rate=r["rejection_rate"],
                hallucination_rate=r["hallucination_rate"],
            )
            for r in data["by_prompt_version"]
        ],
    }
    return report


# --- Prompt versions -------------------------------------------------------


class PromptVersionRead(BaseModel):
    id: str
    company_id: str | None = None
    agent_kind: str
    version: str
    name: str
    description: str | None = None
    content: str
    is_active: bool


class PromptVersionCreate(BaseModel):
    agent_kind: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1)
    description: str | None = None
    company_id: uuid.UUID | None = None
    is_active: bool = False


def _read_prompt(p: PromptVersion) -> PromptVersionRead:
    return PromptVersionRead(
        id=str(p.id),
        company_id=str(p.company_id) if p.company_id else None,
        agent_kind=p.agent_kind,
        version=p.version,
        name=p.name,
        description=p.description,
        content=p.content,
        is_active=p.is_active,
    )


def _scope_prompt(p: PromptVersion, user: User) -> None:
    if (
        p.company_id is not None
        and user.company_id is not None
        and str(p.company_id) != str(user.company_id)
    ):
        raise HTTPException(status_code=403, detail="Недоступно для вашей компании.")


@router.get("/prompts", response_model=list[PromptVersionRead])
def list_prompts(
    agent_kind: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = PromptService(db)
    rows = service.list(company_id=company_scope(user), agent_kind=agent_kind)
    return [_read_prompt(p) for p in rows]


@router.post("/prompts", response_model=PromptVersionRead, status_code=201)
def create_prompt(
    payload: PromptVersionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = PromptService(db)
    company_id = payload.company_id or company_scope(user)
    if (
        payload.company_id is not None
        and user.company_id is not None
        and str(payload.company_id) != str(user.company_id)
    ):
        raise HTTPException(status_code=403, detail="Недоступно для вашей компании.")
    row = service.create(
        company_id=company_id,
        agent_kind=payload.agent_kind,
        version=payload.version,
        name=payload.name,
        content=payload.content,
        description=payload.description,
        is_active=payload.is_active,
    )
    db.commit()
    db.refresh(row)
    return _read_prompt(row)


@router.post("/prompts/{prompt_id}/activate", response_model=PromptVersionRead)
def activate_prompt(
    prompt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = PromptService(db)
    row = service.get(prompt_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Версия промпта не найдена")
    _scope_prompt(row, user)
    service.activate(row)
    db.commit()
    db.refresh(row)
    return _read_prompt(row)


@router.delete("/prompts/{prompt_id}", status_code=204)
def delete_prompt(
    prompt_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = PromptService(db)
    row = service.get(prompt_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Версия промпта не найдена")
    _scope_prompt(row, user)
    db.delete(row)
    db.commit()
