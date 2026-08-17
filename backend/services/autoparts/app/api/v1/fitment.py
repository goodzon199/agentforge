from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.access import ensure_company, ensure_writer
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import PartRequest, User
from app.services.fitment_service import FitmentService

router = APIRouter(prefix="/fitment", tags=["fitment"])


def _load_part_request(db, part_request_id: uuid.UUID, user: User) -> PartRequest:
    pr = db.get(PartRequest, part_request_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    ensure_company(user, pr.company_id)
    return pr


@router.get("/{part_request_id}/explain")
def explain_fitment(
    part_request_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Sprint 4.1 — why the engine believes this pick fits (traffic light +
    evidence tree). Read-only, available to any company user."""
    pr = _load_part_request(db, part_request_id, user)
    return FitmentService(db).explain(pr).to_dict()


class VerifyPayload(BaseModel):
    """A manager's [✓]/[✕] verdict on one article for this request."""

    article: str = Field(..., min_length=1)
    brand: str = ""
    result: str = Field(..., pattern="^(confirmed|rejected)$")


@router.post("/{part_request_id}/verify")
def verify_fitment(
    part_request_id: uuid.UUID,
    payload: VerifyPayload,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Sprint 4.1 — record a manager's fitment verdict as evidence and return
    the fresh explainability view. Requires a company-scoped, non-viewer user."""
    if user.company_id is None:
        raise HTTPException(
            status_code=403, detail="Подтверждать фитмент может пользователь компании."
        )
    ensure_writer(user)
    pr = _load_part_request(db, part_request_id, user)
    service = FitmentService(db)
    service.verify(
        pr,
        user_id=user.id,
        article=payload.article,
        brand=payload.brand,
        result=payload.result,
    )
    db.commit()
    db.refresh(pr)
    return service.explain(pr).to_dict()
