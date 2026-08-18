"""Pack-side implementation of the Agent SDK facades (sprint 5.4).

Every facade here is the autoparts implementation of the SDK contract in
``shared.agents``. A pack agent author never sees this module — they write
against ``ctx`` (AgentContext) and the runtime wires these in.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.models import Agent as AgentRecord
from app.models import AgentAction, TaskEvent
from app.models.enums import AgentActionStatus, ApprovalRiskLevel


@lru_cache(maxsize=1)
def _manifest_permissions() -> set[str]:
    """Permissions the pack declares in manifest.yaml (sprint 5.1/5.4)."""
    import pathlib

    from shared.pack import load_manifest

    for candidate in (
        pathlib.Path(__file__).resolve().parents[2] / "manifest.yaml",
        pathlib.Path("/app/manifest.yaml"),
    ):
        if candidate.is_file():
            try:
                return set(load_manifest(candidate).permissions or [])
            except Exception:
                return set()
    return set()


class AgentMemory:
    """Wraps the pack MemoryService behind the SDK memory facade."""

    def __init__(self, memory_service: Any, agent: AgentRecord) -> None:
        self._service = memory_service
        self._agent = agent

    def remember(self, content: str, kind: str = "interaction") -> Any:
        return self._service.remember_short(self._agent, content, kind=kind)

    def learn(self, content: str, source_task_id: Any = None) -> Any:
        return self._service.remember_long(
            self._agent, content, source_task_id=source_task_id
        )

    def recall(self) -> dict[str, Any]:
        return self._service.build_context(self._agent)

    def search(self, query: str) -> list[Any]:
        return self._service.vector_search(self._agent.company_id, query)

    def knowledge(self, limit: int = 50) -> list[Any]:
        return self._service.knowledge(self._agent.company_id, limit=limit)


class AgentTools:
    """Wraps the pack tool registry behind the SDK tools facade."""

    def __init__(self, registry: Any, allowed: list[str] | None = None) -> None:
        self._registry = registry
        self._allowed = set(allowed or [])

    def run(self, name: str, **kwargs: Any):
        return self._registry.run(name, **kwargs)

    def names(self) -> list[str]:
        return [n for n in self._registry.names() if not self._allowed or n in self._allowed]

    def list(self) -> list[dict[str, Any]]:
        return [t for t in self._registry.list() if not self._allowed or t["name"] in self._allowed]


class AgentActions:
    """Records auditable AgentAction rows behind the SDK actions facade."""

    def __init__(self, db: Any, agent: AgentRecord, task_id: Any = None) -> None:
        self._db = db
        self._agent = agent
        self._task_id = task_id

    def record(
        self,
        action_type: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        input_data: dict[str, Any] | None = None,
        result_data: dict[str, Any] | None = None,
        risk_level: str = "low",
        requires_approval: bool = False,
        idempotency_key: str | None = None,
    ) -> AgentAction:
        action = AgentAction(
            company_id=self._agent.company_id,
            agent_id=self._agent.id,
            task_id=self._task_id,
            action_type=action_type,
            target_type=target_type,
            target_id=target_id,
            input_data=input_data,
            result_data=result_data,
            risk_level=_risk_level(risk_level),
            status=AgentActionStatus.pending,
            requires_approval=requires_approval,
            idempotency_key=idempotency_key,
        )
        self._db.add(action)
        self._db.flush()
        return action


class AgentPermissions:
    """Permission gate from the pack manifest + agent record (sprint 5.4).

    The pack's ``manifest.yaml`` declares the permissions it ships with; an
    agent may additionally carry its own ``permissions``. The gate denies
    anything not declared.
    """

    def __init__(self, agent: AgentRecord) -> None:
        self._allowed: set[str] = set()
        self._allowed.update(_manifest_permissions())
        raw = getattr(agent, "permissions", None) or {}
        if isinstance(raw, dict):
            for values in raw.values():
                if isinstance(values, list):
                    self._allowed.update(str(v) for v in values)
        elif isinstance(raw, list):
            self._allowed.update(str(p) for p in raw)

    def require(self, *permissions: str) -> None:
        missing = [p for p in permissions if p not in self._allowed]
        if missing:
            raise PermissionError(
                f"Агенту запрещено действие: {', '.join(missing)} "
                f"(разрешены: {', '.join(sorted(self._allowed)) or 'нет'})."
            )

    def has(self, permission: str) -> bool:
        return permission in self._allowed

    def allowed(self) -> list[str]:
        return sorted(self._allowed)


class AgentApprovals:
    """Requests a human approval as a pending AgentAction (SDK approvals facade)."""

    def __init__(self, db: Any, agent: AgentRecord, task_id: Any = None) -> None:
        self._db = db
        self._agent = agent
        self._task_id = task_id

    def request(
        self,
        *,
        message: str,
        target_type: str | None = None,
        target_id: str | None = None,
        priority: str = "medium",
    ) -> AgentAction:
        action = AgentAction(
            company_id=self._agent.company_id,
            agent_id=self._agent.id,
            task_id=self._task_id,
            action_type="approval_request",
            target_type=target_type,
            target_id=target_id,
            input_data={"message": message, "priority": priority},
            risk_level=ApprovalRiskLevel.medium if priority == "medium" else ApprovalRiskLevel.high,
            status=AgentActionStatus.pending,
            requires_approval=True,
        )
        self._db.add(action)
        self._db.flush()
        return action


class AgentTrace:
    """Wraps the pack tracer behind the SDK trace facade."""

    def __init__(self, db: Any, agent: AgentRecord) -> None:
        self._db = db
        self._agent = agent

    def span(self, span_type: str, name: str, **metadata: Any):
        from app.tracing.tracer import trace

        return trace(
            self._db,
            span_type,
            name,
            agent_id=self._agent.id,
            metadata=metadata,
        )


class AgentEvents:
    """Emits TaskEvent rows behind the SDK events facade."""

    def __init__(self, db: Any, agent: AgentRecord, task_id: Any = None) -> None:
        self._db = db
        self._agent = agent
        self._task_id = task_id

    def emit(self, message: str, *, level: str = "info", source: str | None = None) -> None:
        self._db.add(
            TaskEvent(
                task_id=self._task_id,
                agent_id=self._agent.id,
                source=source or f"agents.{self._agent.slug}",
                level=level,
                message=message,
                meta={},
            )
        )


def _risk_level(value: str) -> ApprovalRiskLevel:
    try:
        return ApprovalRiskLevel(value)
    except ValueError:
        return ApprovalRiskLevel.low
