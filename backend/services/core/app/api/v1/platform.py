from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.access import company_scope, ensure_writer
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Agent, AgentAction, Company, Task, User
from app.models.enums import AgentActionStatus
from app.services.pack_service import PackError, PackService
from app.services.usage_service import UsageService
from app.services.workflow_service import WorkflowRuntime, WorkflowRuntimeError
from app.tools.registry import tool_registry

router = APIRouter(prefix="/platform", tags=["platform"])


class ApprovalDecision(BaseModel):
    pass


def _scoped_count(
    db: Session, model, scope: uuid.UUID | None, extra=None
) -> int:
    stmt = select(func.count()).select_from(model)
    if scope is not None and hasattr(model, "company_id"):
        stmt = stmt.where(model.company_id == scope)
    if extra is not None:
        stmt = stmt.where(extra)
    return db.scalar(stmt) or 0


def _workflow_payload(w: Any) -> dict[str, Any]:
    return w.model_dump(mode="json")


def _tool_payload(name: str, source: str, pack: str | None = None) -> dict[str, Any]:
    return {"name": name, "source": source, "pack": pack}


@router.get("/overview")
def platform_overview(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Platform-wide counts across the fleet: tenants, packs, workflows,
    tools, tasks and approval load."""
    scope = company_scope(user)
    service = PackService(db)
    packs = service.list()

    workflows_total = 0
    tools_total = 0
    for pack in packs:
        workflows_total += len(pack.workflows or [])
        tools_total += len(pack.tools or [])
    tools_total += len(tool_registry.list())

    return {
        "companies": _scoped_count(db, Company, scope),
        "agents": _scoped_count(db, Agent, scope),
        "agents_active": _scoped_count(db, Agent, scope, Agent.is_active.is_(True)),
        "tasks": _scoped_count(db, Task, scope),
        "tasks_completed": _scoped_count(db, Task, scope, Task.status == "completed"),
        "tasks_failed": _scoped_count(db, Task, scope, Task.status == "failed"),
        "packs": len(packs),
        "packs_active": sum(1 for p in packs if p.is_active),
        "workflows": workflows_total,
        "tools": tools_total,
        "approvals_pending": _scoped_count(
            db,
            AgentAction,
            scope,
            AgentAction.requires_approval.is_(True)
            & (AgentAction.status == AgentActionStatus.pending),
        ),
    }


@router.get("/workflows")
def platform_workflows(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """All workflow definitions shipped by active packs (aggregated)."""
    items: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for pack in PackService(db).list():
        if not pack.is_active:
            continue
        try:
            workflows = WorkflowRuntime(db).load_from_pack(pack)
        except WorkflowRuntimeError as exc:
            errors.append({"pack": pack.name, "error": str(exc)})
            continue
        for workflow in workflows:
            items.append(
                {
                    "pack": pack.name,
                    "name": workflow.name,
                    "version": workflow.version,
                    "start": workflow.start,
                    "nodes": [n.model_dump(mode="json") for n in workflow.nodes],
                }
            )
    return {"workflows": items, "errors": errors}


@router.get("/tools")
def platform_tools(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Tool inventory across packs (manifest) + core tool registry."""
    items: list[dict[str, Any]] = []
    for pack in PackService(db).list():
        for tool in pack.tools or []:
            items.append(_tool_payload(tool, "pack", pack.name))
    for tool in tool_registry.list():
        items.append(_tool_payload(tool["name"], "core", None))
    return {"tools": items}


@router.get("/usage")
def platform_usage(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Metering summary (5.8): tokens, tasks, actions, workflow runs."""
    if days <= 0 or days > 365:
        raise HTTPException(status_code=400, detail="days должен быть в (0, 365].")
    return UsageService(db).summary(days=days, scope=company_scope(user))


@router.get("/approvals")
def platform_approvals(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Pending actions that require human approval (AgentAction rows)."""
    scope = company_scope(user)
    stmt = (
        select(AgentAction)
        .where(
            AgentAction.requires_approval.is_(True),
            AgentAction.status == AgentActionStatus.pending,
        )
        .order_by(AgentAction.created_at.desc())
    )
    if scope is not None:
        stmt = stmt.where(AgentAction.company_id == scope)
    rows = db.scalars(stmt).all()
    return {
        "approvals": [
            {
                "id": str(a.id),
                "company_id": str(a.company_id),
                "agent_id": str(a.agent_id) if a.agent_id else None,
                "task_id": str(a.task_id) if a.task_id else None,
                "action_type": a.action_type,
                "target_type": a.target_type,
                "target_id": a.target_id,
                "risk_level": a.risk_level.value,
                "input_data": a.input_data,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ]
    }


@router.post("/approvals/{approval_id}/approve")
def platform_approval_approve(
    approval_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_writer(user)
    return _decide_approval(db, approval_id, approve=True)


@router.post("/approvals/{approval_id}/reject")
def platform_approval_reject(
    approval_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ensure_writer(user)
    return _decide_approval(db, approval_id, approve=False)


def _decide_approval(
    db: Session, approval_id: uuid.UUID, *, approve: bool
) -> dict[str, Any]:
    action = db.get(AgentAction, approval_id)
    if action is None or not action.requires_approval:
        raise HTTPException(status_code=404, detail="Approval не найден.")
    if action.status != AgentActionStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=f"Approval уже обработан (статус {action.status.value}).",
        )
    action.status = (
        AgentActionStatus.executed if approve else AgentActionStatus.cancelled
    )
    from datetime import UTC, datetime

    action.executed_at = datetime.now(UTC)
    db.commit()
    return {
        "id": str(action.id),
        "status": action.status.value,
        "decided": "approved" if approve else "rejected",
    }


# Re-export for the orchestrator's approval flow (monolith-compatible path).
def pack_error_detail(exc: Exception) -> HTTPException:
    if isinstance(exc, PackError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc
