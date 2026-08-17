from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.emergency import emergency_switch
from app.models import User
from app.services.audit_service import AuditService

router = APIRouter(prefix="/ops", tags=["ops"])

MANAGER_ROLES = frozenset({"owner", "admin"})


class EmergencyStatus(BaseModel):
    engaged: bool
    reason: str | None = None
    engaged_at: str | None = None


class EmergencyEngage(BaseModel):
    reason: str = Field(min_length=1, max_length=500, description="Причина приостановки")


def _require_manager(actor: User) -> None:
    if not actor.is_superuser and actor.role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Операционные команды доступны владельцу или администратору.",
        )


@router.get("/emergency", response_model=EmergencyStatus)
def emergency_status(user: User = Depends(get_current_user)) -> EmergencyStatus:
    return EmergencyStatus(**emergency_switch.status())


@router.post("/emergency/engage", response_model=EmergencyStatus)
def engage_emergency(
    payload: EmergencyEngage,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EmergencyStatus:
    """Pause all agentic work: workers stop consuming the queue, new tasks and
    web-chat messages are rejected until the switch is released."""
    _require_manager(user)
    emergency_switch.engage(payload.reason)
    AuditService(db).record(
        action="emergency.engage",
        entity_type="system",
        user_id=user.id,
        company_id=user.company_id,
        detail={"reason": payload.reason},
    )
    db.commit()
    return EmergencyStatus(**emergency_switch.status())


@router.post("/emergency/release", response_model=EmergencyStatus)
def release_emergency(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EmergencyStatus:
    _require_manager(user)
    emergency_switch.release()
    AuditService(db).record(
        action="emergency.release",
        entity_type="system",
        user_id=user.id,
        company_id=user.company_id,
    )
    db.commit()
    return EmergencyStatus(**emergency_switch.status())
