from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import permissions as perm
from app.core.database import get_db
from app.models import Agent, Company, User
from app.schemas.permissions import (
    PermissionDecisionRead,
    PermissionEvaluateIn,
    PermissionPolicyRead,
    PermissionPolicyUpdateIn,
    PermissionPolicyUpdateRead,
)

router = APIRouter(prefix="/permissions", tags=["permissions"])


def _company(db: Session, user: User) -> Company:
    company = db.get(Company, user.company_id) if user.company_id else None
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    return company


@router.get("/policies", response_model=list[PermissionPolicyRead])
def list_policies(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Effective policy (built-in default + company override) per action."""
    return perm.engine.effective_policies(company=_company(db, user))


@router.put("/policies", response_model=PermissionPolicyUpdateRead)
def update_policies(
    payload: PermissionPolicyUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Override the risk level of actions for this company.

    Keys are action names, optionally ``action:resource``; values must be
    ``low`` / ``medium`` / ``high`` (case-insensitive). An empty map clears
    all overrides.
    """
    company = _company(db, user)
    normalized: dict[str, str] = {}
    for key, level in payload.permissions.items():
        normalized[key] = level.upper()
        try:
            perm.ApprovalRiskLevel(level.upper())
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Недопустимый уровень риска «{level}» для «{key}».",
            ) from None
    settings = dict(company.settings or {})
    settings["permissions"] = normalized
    company.settings = settings
    db.commit()
    return PermissionPolicyUpdateRead(permissions=normalized)


@router.post("/evaluate", response_model=PermissionDecisionRead)
def evaluate_action(
    payload: PermissionEvaluateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ask the engine: may this agent perform this action in my company?"""
    company = _company(db, user)
    agent = None
    if payload.agent_id is not None:
        agent = db.get(Agent, payload.agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Агент не найден")
    decision = perm.evaluate(
        agent=agent,
        company=company,
        action=payload.action,
        resource=payload.resource,
        context=payload.context,
    )
    return PermissionDecisionRead(**decision.to_dict())
