from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Task, User
from app.services.pack_service import PackError, PackService
from app.services.workflow_service import WorkflowRuntime, WorkflowRuntimeError

router = APIRouter(prefix="/workflows", tags=["workflows"])

MANAGER_ROLES = frozenset({"owner", "admin"})


class WorkflowRunRequest(BaseModel):
    pack: str = Field(min_length=1)
    workflow: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None


def _require_manager(actor: User) -> None:
    if not actor.is_superuser and actor.role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Управление workflow доступно владельцу или администратору.",
        )


@router.get("/{pack}/workflows")
def list_pack_workflows(
    pack: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        pack_record = PackService(db).get(pack)
        workflows = WorkflowRuntime(db).load_from_pack(pack_record)
    except (PackError, WorkflowRuntimeError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"workflows": [w.model_dump(mode="json") for w in workflows]}


@router.post("/{pack}/{workflow}/run")
def run_workflow(
    pack: str,
    workflow: str,
    payload: WorkflowRunRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Execute a pack workflow DAG against an existing task.

    Core's orchestrator creates a Task, then the runtime walks the workflow
    DAG: agent nodes dispatch to the active pack that provides them, condition
    nodes branch on the run context, human nodes record a pending AgentAction.
    """
    _require_manager(user)
    if payload.task_id:
        task = db.get(Task, uuid.UUID(payload.task_id))
        if task is None:
            raise HTTPException(status_code=404, detail="Задача не найдена.")
    else:
        raise HTTPException(
            status_code=400,
            detail="task_id обязателен: workflow исполняется в контексте задачи.",
        )
    try:
        pack_record = PackService(db).get(pack)
        runtime = WorkflowRuntime(db)
        definition = runtime.load_named(pack_record, workflow)
        result = runtime.run(
            task, definition, payload.context, owning_pack=pack_record
        )
    except (PackError, WorkflowRuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return result
