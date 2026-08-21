from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_sales_service
from app.models import User
from app.schemas.sales import AgentActionRead
from app.services.sales_service import SalesService, company_allowed

router = APIRouter(prefix="/actions", tags=["actions"])


def _read(action) -> AgentActionRead:
    return AgentActionRead(
        id=action.id,
        company_id=action.company_id,
        agent_id=action.agent_id,
        task_id=action.task_id,
        action_type=action.action_type,
        target_type=action.target_type,
        target_id=action.target_id,
        input_data=action.input_data,
        result_data=action.result_data,
        risk_level=action.risk_level.value,
        status=action.status.value,
        requires_approval=action.requires_approval,
        idempotency_key=action.idempotency_key,
        created_at=action.created_at,
        executed_at=action.executed_at,
    )


@router.get("", response_model=list[AgentActionRead])
def list_actions(
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    return [_read(a) for a in service.list_actions(company_id=user.company_id)]


@router.get("/{action_id}", response_model=AgentActionRead)
def get_action(
    action_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    action = service.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Действие не найдено")
    if not company_allowed(user, action.company_id):
        raise HTTPException(status_code=403, detail="Действие принадлежит другой компании")
    return _read(action)
