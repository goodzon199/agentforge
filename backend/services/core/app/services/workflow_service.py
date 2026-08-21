from __future__ import annotations

import copy
import logging
from typing import Any

import httpx
from shared.internal import internal_headers
from shared.pack import PackState
from shared.workflow import (
    ConditionError,
    NodeType,
    Workflow,
    WorkflowError,
    WorkflowNode,
    evaluate_condition,
    parse_workflow,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AgentAction, Pack
from app.models.enums import AgentActionStatus, ApprovalRiskLevel

logger = logging.getLogger(__name__)


class WorkflowRuntimeError(RuntimeError):
    """Raised when a workflow cannot be loaded or executed."""


class WorkflowRuntime:
    """Executes declarative pack workflows (sprint 5.3).

    A workflow is a DAG of nodes shipped by a pack (``workflow.yaml`` in the
    pack, exposed via /internal/pack/workflows). Core loads the definitions
    over the internal contract, validates them with the shared SDK and walks
    the graph:

    - ``agent`` nodes run the agent in the pack that declares it (remote
      dispatch over /internal/agents/execute)
    - ``condition`` nodes evaluate a safe boolean expression over the run
      context and branch true/false
    - ``human`` nodes pause the run: an AgentAction is recorded so an
      operator can approve/resume
    - ``end`` nodes finish the run

    The accumulated per-node outputs are folded into a single result dict.
    """

    def __init__(self, db: Session):
        self.db = db

    # --- Loading -----------------------------------------------------------

    def load_from_pack(self, pack: Pack) -> list[Workflow]:
        """Fetch and validate all workflow definitions from one pack."""
        try:
            resp = httpx.get(
                f"{pack.base_url.rstrip('/')}/internal/pack/workflows",
                headers=internal_headers(),
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise WorkflowRuntimeError(
                f"load workflows pack {pack.name!r}: {exc}"
            ) from exc

        workflows: list[Workflow] = []
        for raw in data.get("workflows", []):
            try:
                workflows.append(parse_workflow(raw))
            except WorkflowError as exc:
                raise WorkflowRuntimeError(
                    f"pack {pack.name!r}: невалидный workflow: {exc}"
                ) from exc
        return workflows

    def load_named(self, pack: Pack, name: str) -> Workflow:
        for workflow in self.load_from_pack(pack):
            if workflow.name == name:
                return workflow
        raise WorkflowRuntimeError(
            f"pack {pack.name!r} не поставляет workflow {name!r}."
        )

    def resolve_pack(self, name: str) -> Pack:
        pack = self.db.scalars(
            select(Pack).where(
                Pack.name == name,
                Pack.is_active.is_(True),
                Pack.state == PackState.active,
            )
        ).first()
        if pack is None:
            raise WorkflowRuntimeError(f"Pack {name!r} не активен.")
        return pack

    # --- Execution ---------------------------------------------------------

    def run(
        self,
        task,
        workflow: Workflow,
        context: dict[str, Any] | None = None,
        *,
        owning_pack: Pack | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow DAG for a task. Returns the accumulated output."""
        run_context: dict[str, Any] = dict(context or {})
        run_context.setdefault("task_id", str(task.id))
        run_context.setdefault("objective", task.objective)
        run_context.setdefault("input_data", task.input_data or {})

        current = workflow.node(workflow.start)
        if current is None:
            raise WorkflowRuntimeError(f"start {workflow.start!r} не найден.")
        if task is not None:
            self._add_event(
                task,
                f"workflow {workflow.name} стартует с {current.id}.",
                meta={
                    "workflow": workflow.name,
                    "pack": owning_pack.name if owning_pack else None,
                },
            )

        visited: set[str] = set()
        steps: list[dict[str, Any]] = []
        status = "completed"
        paused_node: str | None = None

        while current is not None:
            if current.id in visited:
                raise WorkflowRuntimeError(
                    f"workflow {workflow.name}: цикл на node {current.id!r}."
                )
            visited.add(current.id)

            if current.type == NodeType.agent:
                output = self._run_agent_node(
                    task, current, run_context, owning_pack=owning_pack
                )
                steps.append({"node": current.id, "type": "agent", "output": output})
                for key, value in (output.get("data", {}) or {}).items():
                    run_context[key] = copy.deepcopy(value)
                run_context["output"] = copy.deepcopy(output)
                current = workflow.node(current.next) if current.next else None

            elif current.type == NodeType.condition:
                try:
                    decision = evaluate_condition(
                        current.expression or "", run_context
                    )
                except ConditionError as exc:
                    raise WorkflowRuntimeError(
                        f"node {current.id!r}: {exc}"
                    ) from exc
                steps.append({"node": current.id, "type": "condition", "decision": decision})
                current = workflow.node(current.branches["true" if decision else "false"])

            elif current.type == NodeType.human:
                action = self._record_human_step(task, current, run_context)
                steps.append(
                    {
                        "node": current.id,
                        "type": "human",
                        "action_id": str(action.id),
                        "status": action.status.value,
                    }
                )
                status = "awaiting_approval"
                paused_node = current.id
                break

            elif current.type == NodeType.end:
                steps.append(
                    {
                        "node": current.id,
                        "type": "end",
                        "message": current.message,
                    }
                )
                current = None

        result = {
            "workflow": workflow.name,
            "status": status,
            "paused_at": paused_node,
            "steps": steps,
            "context": run_context,
        }
        if task is not None:
            self._add_event(
                task,
                f"workflow {workflow.name} завершён со статусом {status}.",
            )
        return result

    # --- Node handlers -----------------------------------------------------

    def _run_agent_node(
        self, task, node: WorkflowNode, context: dict[str, Any], *, owning_pack: Pack | None = None
    ) -> dict[str, Any]:
        """Dispatch an agent node to the active pack that provides the agent.

        The workflow's own pack is preferred so two verticals declaring the
        same agent type (e.g. ``sales`` in autoparts and beauty) do not
        collide; other active packs are the fallback.
        """
        pack = self._pack_for_agent(node.agent or "", prefer=owning_pack)
        if pack is None:
            raise WorkflowRuntimeError(
                f"никто из активных packs не поставляет агента {node.agent!r}."
            )
        if task is not None:
            self._add_event(
                task,
                f"workflow node {node.id}: агент {node.agent} "
                f"(pack {pack.name}, internal contract).",
            )
        try:
            resp = httpx.post(
                f"{pack.base_url.rstrip('/')}/internal/agents/execute",
                headers=internal_headers(),
                json={
                    "agent_type": node.agent,
                    "objective": context.get("objective", ""),
                    "input_data": self._agent_input_data(context),
                },
                timeout=settings.llm_read_timeout + 10.0,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise WorkflowRuntimeError(
                f"node {node.id!r}: remote агент {node.agent!r} не выполнился: {exc}"
            ) from exc

    def _agent_input_data(self, context: dict[str, Any]) -> dict[str, Any]:
        """Thread accumulated run context into the next agent node.

        Agent outputs are folded into ``run_context`` top-level keys as the
        DAG walks (e.g. ``service``/``day`` from reception). A progressive
        pipeline needs those values visible to the next agent, so we merge
        the original task ``input_data`` with every accumulated context key.
        Reserved keys (task_id/objective/input_data/output) are excluded.
        """
        reserved = {"task_id", "objective", "input_data", "output"}
        merged = dict(context.get("input_data", {}) or {})
        for key, value in context.items():
            if key not in reserved:
                merged[key] = copy.deepcopy(value)
        return merged

    def _pack_for_agent(self, agent_type: str, *, prefer: Pack | None = None) -> Pack | None:
        """Find an active pack that provides ``agent_type``.

        ``prefer`` (the workflow's owning pack) wins ties: agent types are not
        globally unique across verticals, so a workflow must dispatch to its own
        pack first.
        """
        packs = self.db.scalars(
            select(Pack).where(
                Pack.is_active.is_(True),
                Pack.state == PackState.active,
            )
        ).all()
        if prefer is not None and any(
            a.get("type") == agent_type for a in (prefer.agents or [])
        ):
            return prefer
        for pack in packs:
            if any(a.get("type") == agent_type for a in (pack.agents or [])):
                return pack
        return None

    def _record_human_step(
        self, task, node: WorkflowNode, context: dict[str, Any]
    ) -> AgentAction:
        action = AgentAction(
            company_id=task.company_id,
            agent_id=task.agent_id,
            task_id=task.id,
            action_type="workflow_human",
            target_type="workflow",
            target_id=str(task.id),
            input_data={
                "node_id": node.id,
                "message": node.message,
                "priority": node.priority,
                "context": context,
            },
            risk_level=ApprovalRiskLevel.medium,
            status=AgentActionStatus.pending,
            requires_approval=True,
        )
        self.db.add(action)
        self.db.flush()
        return action

    def _add_event(self, task, message: str, *, meta: dict[str, Any] | None = None) -> None:
        from app.models import TaskEvent

        self.db.add(
            TaskEvent(
                task_id=task.id,
                agent_id=task.agent_id,
                source="workflow_runtime",
                level="info",
                message=message,
                meta=meta or {},
            )
        )
