from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models import User
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


class PipelineStageStats(BaseModel):
    objective: str
    count: int
    failed: int
    avg_seconds: float | None = None
    p95_seconds: float | None = None
    sla_seconds: float
    on_sla_pct: float | None = None


class PilotAnalytics(BaseModel):
    period_days: int
    requests_total: int
    conversations_total: int
    ai_handled: int
    handed_to_manager: int
    takeover_rate: float
    part_requests_total: int
    quotes_sent: int
    quotes_accepted: int
    orders_total: int
    revenue: str
    gross_profit: str
    avg_response_seconds: float | None = None
    pipeline: list[PipelineStageStats]
    suppliers: dict[str, Any]
    llm: dict[str, Any]
    task_timeouts: int


@router.get("/pilot", response_model=PilotAnalytics)
def pilot_analytics(
    days: int = 1,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = AnalyticsService(db).pilot(company_id=user.company_id, days=days)
    return PilotAnalytics(**data)
