from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.access import company_scope, ensure_company
from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import Company, Conversation, PartRequest, User
from app.models.shadow_comparison import ShadowComparison
from app.services.manager_dashboard_service import ManagerDashboardService
from app.services.shadow_service import ShadowService

router = APIRouter(prefix="/manager", tags=["manager"])


def _comparison_read(comparison: ShadowComparison) -> dict:
    return {
        "id": str(comparison.id),
        "part_request_id": str(comparison.part_request_id),
        "conversation_id": str(comparison.conversation_id),
        "status": comparison.status,
        "ai": {
            "vehicle": comparison.ai_vehicle,
            "part": comparison.ai_part,
            "article": comparison.ai_article,
            "offer_ids": comparison.ai_offer_ids or [],
            "price": str(comparison.ai_price) if comparison.ai_price is not None else None,
            "answer": comparison.ai_answer,
        },
        "manager": {
            "vehicle": comparison.manager_vehicle,
            "part": comparison.manager_part,
            "article": comparison.manager_article,
            "offer_ids": comparison.manager_offer_ids or [],
            "price": str(comparison.manager_price)
            if comparison.manager_price is not None
            else None,
            "reply": comparison.manager_reply,
        },
        "result": {
            "vehicle_match": comparison.vehicle_match,
            "part_match": comparison.part_match,
            "oem_match": comparison.oem_match,
            "offer_overlap": comparison.offer_overlap,
            "price_delta": str(comparison.price_delta)
            if comparison.price_delta is not None
            else None,
            "time_seconds": comparison.time_seconds,
        },
        "evaluated_at": comparison.evaluated_at.isoformat()
        if comparison.evaluated_at
        else None,
        "created_at": comparison.created_at.isoformat(),
    }


def _load_part_request(db, part_request_id: uuid.UUID, user: User) -> PartRequest:
    pr = db.get(PartRequest, part_request_id)
    if pr is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    ensure_company(user, pr.company_id)
    return pr


def _load_conversation(db, conversation_id: uuid.UUID, user: User) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    ensure_company(user, conv.company_id)
    return conv


@router.get("/dashboard")
def manager_dashboard(
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """The manager's main screen: where attention is needed, what AI did
    today, and the queue of things to do right now (sprint 3.8)."""
    scope = company_scope(user)
    if scope is None:
        raise HTTPException(
            status_code=403, detail="Доступ к главному экрану имеет пользователь компании."
        )
    return ManagerDashboardService(db).dashboard(scope)


class ShadowSubmit(BaseModel):
    part_request_id: uuid.UUID
    vehicle: str = ""
    part: str = ""
    article: str = ""
    offer_ids: list[str] = Field(default_factory=list)
    price: float | None = None
    reply: str = ""


@router.get("/shadow")
def list_shadow(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    scope = company_scope(user)
    if scope is None:
        raise HTTPException(status_code=403, detail="Shadow-панель доступна пользователю компании.")
    service = ShadowService(db)
    return {
        "items": [_comparison_read(c) for c in service.list_for_company(scope, limit=limit)],
        "stats": service.stats(scope),
        "shadow_mode": _shadow_mode(db, scope),
    }


@router.post("/shadow/submit")
def submit_shadow(
    payload: ShadowSubmit,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """The manager submits their own selection for a request; it is compared
    with what Agentos produced, and (in shadow mode) only the manager's reply
    reaches the customer."""
    pr = _load_part_request(db, payload.part_request_id, user)
    service = ShadowService(db)
    comparison = service.submit_manager(
        pr,
        vehicle=payload.vehicle,
        part=payload.part,
        article=payload.article,
        offer_ids=payload.offer_ids,
        price=payload.price,
        reply=payload.reply,
    )
    if payload.reply:
        conversation = _load_conversation(db, pr.conversation_id, user)
        service.add_manager_reply(
            conversation, comparison, user_id=user.id
        )
    db.commit()
    return _comparison_read(comparison)


@router.get("/shadow/stats")
def shadow_stats(
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    scope = company_scope(user)
    if scope is None:
        raise HTTPException(status_code=403, detail="Shadow-панель доступна пользователю компании.")
    stats = ShadowService(db).stats(scope)
    stats["shadow_mode"] = _shadow_mode(db, scope)
    return stats


class ShadowModePayload(BaseModel):
    enabled: bool


@router.patch("/shadow-mode")
def set_shadow_mode(
    payload: ShadowModePayload,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Toggle shadow mode for the company (sprint 3.8.1)."""
    scope = company_scope(user)
    if scope is None:
        raise HTTPException(status_code=403, detail="Настройка доступна пользователю компании.")
    company = db.get(Company, scope)
    if company is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")
    company.shadow_mode = payload.enabled
    db.commit()
    return {"shadow_mode": company.shadow_mode}


def _shadow_mode(db, company_id: uuid.UUID) -> bool:
    company = db.get(Company, company_id)
    return bool(company.shadow_mode) if company is not None else False
