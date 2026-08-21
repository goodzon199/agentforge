"""Internal contract for the Beauty pack (sprint 5.5).

Token-gated endpoints core calls over HTTP: manifest, health, migrate
(no-op — the pack has no database), workflows and agent dispatch. Everything
here is built on the shared SDK; the pack never imports core code.
"""

from __future__ import annotations

import pathlib
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from shared.agents import run_agent
from shared.internal import require_internal_token
from shared.pack import ManifestError, load_manifest
from shared.workflow import WorkflowError, load_workflow

from app.agents import get_class
from app.salon import state as salon_state

_lock = threading.Lock()

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
)


class AgentExecuteRequest(BaseModel):
    agent_type: str
    objective: str
    input_data: dict[str, Any] = {}
    task_id: str | None = None
    company_id: str | None = None
    # Sprint 5.8.3 Pack Context Contract: same dispatch shape as autoparts.
    dispatch_id: str | None = None
    context: dict[str, Any] = {}


@router.get("/health")
def internal_health() -> dict[str, str]:
    return {"status": "ok", "service": "beauty"}


@router.get("/metrics")
def internal_metrics() -> dict[str, Any]:
    """Pack metrics over the internal contract (sprint 5.8.2).

    The Beauty pack has no database, so its numbers are derived from the
    in-memory salon calendar: bookings made, revenue at catalog prices and
    the number of bookable services.
    """
    from app.salon import SERVICES
    from app.salon import state as salon_state

    bookings = list(salon_state._bookings.values())
    revenue = sum(
        SERVICES[b.service_key].price_rub
        for b in bookings
        if b.service_key in SERVICES
    )
    return {
        "namespace": "beauty",
        "metrics": {
            "appointments": len(bookings),
            "revenue": revenue,
            "services": len(SERVICES),
        },
    }


@router.get("/pack/manifest")
def pack_manifest() -> dict[str, Any]:
    """Expose manifest.yaml to core for discovery (sprint 5.1)."""
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
    raise HTTPException(status_code=500, detail="manifest.yaml не найден.")


@router.post("/pack/migrate")
def pack_migrate() -> dict[str, Any]:
    """No-op: the Beauty pack has no database (sprint 5.5)."""
    return {"ok": True, "revision": "noop-none"}


@router.get("/pack/workflows")
def pack_workflows() -> dict[str, Any]:
    """Expose workflow definitions to core (sprint 5.3)."""
    workflows_dir = pathlib.Path(__file__).resolve().parents[2] / "workflows"
    if not workflows_dir.is_dir():
        return {"workflows": []}
    loaded: list[dict[str, Any]] = []
    for file_path in sorted(workflows_dir.glob("*.yaml")):
        try:
            workflow = load_workflow(file_path)
        except WorkflowError:
            continue
        loaded.append(workflow.model_dump(mode="json"))
    return {"workflows": loaded}


@router.post("/agents/execute")
def agent_execute(payload: AgentExecuteRequest) -> dict[str, Any]:
    """Run a Beauty agent over the internal contract (sprint 5.4/5.5)."""
    try:
        agent_cls = get_class(payload.agent_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    agent = agent_cls()
    with _lock:
        ctx = agent.build_context(
            objective=payload.objective,
            input_data=payload.input_data or {},
            task_id=payload.task_id,
            company_id=payload.company_id,
            dispatch_id=payload.dispatch_id,
            context=payload.context or {},
        )
        try:
            output = run_agent(agent, ctx)
        finally:
            # The in-memory salon state survives across calls; the run-scoped
            # audit/memory facades do not need cleanup.
            _ = salon_state
    return {
        "response": output.response,
        "data": output.data,
        "handoff_agent": output.handoff_agent,
        "routing_decision": output.routing_decision,
    }
