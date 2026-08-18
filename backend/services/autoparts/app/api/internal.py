from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from shared.internal import require_internal_token
from shared.pack import ManifestError, load_manifest
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Conversation, PartRequest, Quote

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


class CustomerMessageEvent(BaseModel):
    company_id: str
    conversation_id: str
    content: str


class PartsSearchRequest(BaseModel):
    part_request_id: str
    triggered_by: str = "agent"


class PartsPriceRequest(BaseModel):
    part_request_id: str
    run_id: str | None = None


class QuotePrepareDraftRequest(BaseModel):
    quote_id: str
    task_id: str | None = None


class QuoteSendRequest(BaseModel):
    quote_id: str
    message: str | None = None
    user_id: str
    approve_now: bool = False


class AgentExecuteRequest(BaseModel):
    agent_type: str
    objective: str
    input_data: dict[str, Any] = {}


def _get_or_404(db: Session, model, entity_id: str):
    try:
        record = db.get(model, uuid.UUID(entity_id))
    except (ValueError, TypeError):
        record = None
    if record is None:
        raise HTTPException(status_code=404, detail="Сущность не найдена.")
    return record


@router.post("/agents/execute")
def agent_execute(payload: AgentExecuteRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Run a domain agent over the internal contract (orchestration dispatch).

    Core's SystemAgent routes a task to a domain agent; core has no domain
    agent implementations, so it posts here with agent_type + objective +
    input_data and the domain side executes it with its own registry.
    """
    from app.agents.registry import agent_registry
    from app.orchestrator.orchestrator import orchestrator

    agent_cls = agent_registry.get_class(payload.agent_type)
    agent_record = orchestrator._resolve_agent_by_type(db, payload.agent_type)
    if agent_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Агент {payload.agent_type} не найден в базе.",
        )
    from app.llm.client import llm_client
    from app.memory.service import MemoryService
    from app.tools.registry import tool_registry

    agent = agent_cls(
        record=agent_record,
        memory=MemoryService(db),
        tools=tool_registry,
        llm=llm_client,
        db=db,
    )
    output = agent.execute(payload.objective, payload.input_data)
    return {
        "response": output.response,
        "data": output.data,
        "handoff_agent": output.handoff_agent,
        "routing_decision": output.routing_decision,
    }


@router.post("/events/customer-message")
def on_customer_message(payload: CustomerMessageEvent, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Domain handling of an incoming customer message (contract §3).

    Core emits this for every customer message; the domain decides whether it
    confirms a sent quote (accept-on-confirm) or triggers new intake work.
    """
    conversation = _get_or_404(db, Conversation, payload.conversation_id)
    from app.services.order_service import OrderService

    result = OrderService(db).accept_if_customer_confirms(
        conversation, payload.content
    )
    db.commit()
    return {"accepted": result is not None, "result": result}


@router.post("/parts/search")
def parts_search(payload: PartsSearchRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.services.parts_search_service import PartsSearchService

    pr = _get_or_404(db, PartRequest, payload.part_request_id)
    result = PartsSearchService(db).search(pr, triggered_by=payload.triggered_by)
    db.commit()
    return result


@router.post("/parts/price")
def parts_price(payload: PartsPriceRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.services.pricing_service import PricingService

    result = PricingService(db).process(
        uuid.UUID(payload.part_request_id),
        uuid.UUID(payload.run_id) if payload.run_id else None,
        triggered_by="agent",
    )
    db.commit()
    return result


@router.post("/quotes/prepare-draft")
def quote_prepare_draft(payload: QuotePrepareDraftRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.services.sales_service import SalesService

    quote = _get_or_404(db, Quote, payload.quote_id)
    result = SalesService(db).generate_draft(quote)
    db.commit()
    return result


@router.post("/quotes/send")
def quote_send(payload: QuoteSendRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.models import User
    from app.services.sales_service import SalesService

    quote = _get_or_404(db, Quote, payload.quote_id)
    user = db.get(User, uuid.UUID(payload.user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
    result = SalesService(db).request_send(
        quote,
        payload.message,
        user,
        approve_now=payload.approve_now,
    )
    db.commit()
    return result


@router.get("/health")
def internal_health() -> dict[str, str]:
    return {"status": "ok", "service": "autoparts"}


@router.get("/pack/manifest")
def pack_manifest() -> dict[str, Any]:
    """Expose this pack's manifest.yaml to core for discovery (sprint 5.1).

    Core reads the manifest over the internal contract and registers the
    pack; no pack-side registration is needed. The manifest lives at the
    service root (``manifest.yaml``), also copied into the image at /app.
    """
    import pathlib

    candidates = [
        pathlib.Path(__file__).resolve().parents[2] / "manifest.yaml",
        pathlib.Path("/app/manifest.yaml"),
        pathlib.Path.cwd() / "manifest.yaml",
    ]
    for path in candidates:
        if path.is_file():
            try:
                manifest = load_manifest(path)
            except ManifestError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return {
                "name": manifest.name,
                "version": manifest.version,
                "manifest": manifest.model_dump(mode="json"),
            }
    raise HTTPException(
        status_code=500,
        detail="manifest.yaml не найден в пакете autoparts.",
    )


@router.post("/pack/migrate")
def pack_migrate() -> dict[str, Any]:
    """Apply this pack's alembic migrations up to head (sprint 5.2).

    Core calls this during install/upgrade so a new vertical never needs
    manual DB work. Returns the revision head now applied.
    """
    from app.core.pack_migrations import upgrade_to_head

    try:
        revision = upgrade_to_head()
    except Exception as exc:
        logger.exception("pack migrate failed")
        raise HTTPException(status_code=500, detail=f"migrate failed: {exc}") from exc
    return {"ok": True, "revision": revision}
