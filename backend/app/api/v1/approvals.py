from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user, get_sales_service
from app.models import User
from app.schemas.sales import (
    ApprovalActionResult,
    ApprovalRead,
    ApprovalRejectIn,
)
from app.services.sales_service import (
    ConflictError,
    ForbiddenError,
    GuardBlockedError,
    NotFoundError,
    SalesService,
    company_allowed,
)

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _read(approval) -> ApprovalRead:
    return ApprovalRead(
        id=approval.id,
        company_id=approval.company_id,
        task_id=approval.task_id,
        conversation_id=approval.conversation_id,
        quote_id=approval.quote_id,
        action_id=approval.action_id,
        action_type=approval.action_type,
        status=approval.status.value,
        payload=approval.payload,
        risk_level=approval.risk_level.value,
        requested_by_agent_id=approval.requested_by_agent_id,
        approved_by_user_id=approval.approved_by_user_id,
        approved_at=approval.approved_at,
        rejected_by_user_id=approval.rejected_by_user_id,
        rejected_at=approval.rejected_at,
        rejection_reason=approval.rejection_reason,
        created_at=approval.created_at,
        expires_at=approval.expires_at,
    )


def _handle(exc: Exception):
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ForbiddenError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, GuardBlockedError):
        raise HTTPException(status_code=422, detail={"guard": exc.guard})
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail=str(exc))
    raise exc


@router.get("", response_model=list[ApprovalRead])
def list_approvals(
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    return [_read(a) for a in service.list_approvals(company_id=user.company_id)]


@router.get("/{approval_id}", response_model=ApprovalRead)
def get_approval(
    approval_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    approval = service.get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Запрос на согласование не найден")
    if not company_allowed(user, approval.company_id):
        raise HTTPException(status_code=403, detail="Запрос принадлежит другой компании")
    return _read(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalActionResult)
def approve_approval(
    approval_id: uuid.UUID,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    try:
        result = service.approve(approval_id, user)
    except Exception as exc:  # noqa: BLE001 - unified error mapping
        _handle(exc)
    return ApprovalActionResult(**result)


@router.post("/{approval_id}/reject", response_model=ApprovalActionResult)
def reject_approval(
    approval_id: uuid.UUID,
    payload: ApprovalRejectIn,
    user: User = Depends(get_current_user),
    service: SalesService = Depends(get_sales_service),
):
    try:
        result = service.reject(approval_id, user, payload.rejection_reason)
    except Exception as exc:  # noqa: BLE001 - unified error mapping
        _handle(exc)
    return ApprovalActionResult(**result)
