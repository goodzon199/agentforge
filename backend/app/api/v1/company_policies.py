from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.schemas.company_policies import (
    CompanyPoliciesRead,
    CompanyPoliciesUpdateIn,
)
from app.services.company_policy_service import CompanyPolicyService

router = APIRouter(prefix="/company-policies", tags=["company-policies"])


def _read(db: Session, user: User) -> CompanyPoliciesRead:
    service = CompanyPolicyService(db)
    effective = service.effective(user.company_id)
    return CompanyPoliciesRead(
        company_id=user.company_id,
        pricing=effective["pricing"],
        supplier=effective["supplier"],
        approval=effective["approval"],
        sales=effective["sales"],
        security=effective["security"],
        defaults=service.defaults(),
    )


@router.get("", response_model=CompanyPoliciesRead)
def get_policies(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.company_id is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    return _read(db, user)


@router.put("", response_model=CompanyPoliciesRead)
def update_policies(
    payload: CompanyPoliciesUpdateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Partial update of any policy domain. Omitted domains keep their values."""
    if user.company_id is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    try:
        CompanyPolicyService(db).update(
            user.company_id,
            pricing=payload.pricing,
            supplier=payload.supplier,
            approval=payload.approval,
            sales=payload.sales,
            security=payload.security,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _read(db, user)
