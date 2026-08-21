"""Agent SDK (sprint 5.4).

A pack developer writes an agent without touching core or pack internals:

    from shared.agents import Agent, AgentContext, AgentOutput, AgentRegistry

    class LeadAgent(Agent):
        name = "lead-agent"
        permissions = ["crm.read", "crm.write"]

        def execute(self, ctx: AgentContext) -> AgentOutput:
            ...

``ctx`` (AgentContext) is the only dependency an agent author needs to learn.
It exposes capabilities as facades:

    ctx.objective / ctx.input_data        run inputs
    ctx.memory                            remember / recall / search
    ctx.tools                             run tools (ToolRegistry)
    ctx.actions                           record auditable actions
    ctx.permissions                       permission gate
    ctx.approvals                         request a human approval
    ctx.trace                             open a span
    ctx.llm                               chat / embed
    ctx.events                            emit task events
    ctx.db                                optional escape hatch

This module is pure Python (pydantic only) — no SQLAlchemy, no services. The
pack runtime injects concrete facades when building a context.
"""

from __future__ import annotations

import abc
import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass
class AgentOutput:
    """Contract every agent returns from ``execute``."""

    response: str
    data: dict[str, Any] = field(default_factory=dict)
    routing_decision: dict[str, Any] = field(default_factory=dict)
    handoff_agent: str | None = None


class ToolResult(BaseModel):
    """Result of a tool run (shared with the Tool SDK)."""

    ok: bool = True
    data: Any = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Facade protocols (the surface an agent author sees on ctx)
# ---------------------------------------------------------------------------


class MemoryFacade:
    """Memory the agent may read/write during a run."""

    def remember(self, content: str, kind: str = "interaction") -> Any:
        raise NotImplementedError

    def learn(self, content: str, source_task_id: Any = None) -> Any:
        raise NotImplementedError

    def recall(self) -> dict[str, Any]:
        raise NotImplementedError

    def search(self, query: str) -> list[Any]:
        raise NotImplementedError


class ToolsFacade:
    """Tool access the agent is granted."""

    def run(self, name: str, **kwargs: Any) -> ToolResult:
        raise NotImplementedError

    def names(self) -> list[str]:
        raise NotImplementedError

    def list(self) -> list[dict[str, Any]]:
        raise NotImplementedError


class ActionsFacade:
    """Record what the agent did (auditable, risk-scored)."""

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
    ) -> Any:
        raise NotImplementedError


class PermissionsFacade:
    """Declared permission gate (from the manifest, enforced by the runtime)."""

    def require(self, *permissions: str) -> None:
        raise NotImplementedError

    def has(self, permission: str) -> bool:
        raise NotImplementedError

    def allowed(self) -> list[str]:
        raise NotImplementedError


class ApprovalsFacade:
    """Request a human approval / confirmation during a run."""

    def request(
        self,
        *,
        message: str,
        target_type: str | None = None,
        target_id: str | None = None,
        priority: str = "medium",
    ) -> Any:
        raise NotImplementedError


class TraceFacade:
    """Open/close a span in the current trace."""

    def span(self, span_type: str, name: str, **metadata: Any) -> Any:
        raise NotImplementedError


class LLMFacade:
    """LLM chat/embed access (records usage per task automatically)."""

    def chat(
        self,
        messages: list[Any],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        raise NotImplementedError

    def embed(self, text: str, *, model: str | None = None) -> list[float] | None:
        raise NotImplementedError


class EventsFacade:
    """Emit structured task events (visible in task timeline / logs)."""

    def emit(self, message: str, *, level: str = "info", source: str | None = None) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class AgentContext:
    """Everything an agent may touch during ``execute``.

    Facades are injected by the pack runtime; agents never construct them.

    Sprint 5.8.3 Pack Context Contract: core stays the source of truth for
    company/user/customer/conversation/message and ships exactly the context
    a run needs at remote dispatch. Agents read ``ctx.tenant / ctx.customer /
    ctx.conversation / ctx.message / ctx.history`` and never query another
    service's storage; the pack stores only its own domain data plus
    ``core_*`` references.
    """

    objective: str
    input_data: dict[str, Any] = field(default_factory=dict)

    # Run identity (optional, pack runtime fills these).
    agent: Any = None  # agent record/identity
    agent_id: Any = None
    company_id: Any = None
    task_id: Any = None

    # Dispatch identity (idempotency): stable per task, unique per attempt.
    dispatch_id: str | None = None

    # Pack Context Contract payloads (plain dicts, core-owned truth).
    tenant: dict[str, Any] = field(default_factory=dict)       # {"company_id"}
    customer: dict[str, Any] = field(default_factory=dict)     # {"id", "name", ...}
    conversation: dict[str, Any] = field(default_factory=dict) # {"id", "channel"}
    message: dict[str, Any] = field(default_factory=dict)      # {"id", "text"}
    history: list[Any] = field(default_factory=list)           # [{sender, text}, ...]

    # Capabilities — pack-provided facades.
    memory: MemoryFacade | None = None
    tools: ToolsFacade | None = None
    actions: ActionsFacade | None = None
    permissions: PermissionsFacade | None = None
    approvals: ApprovalsFacade | None = None
    trace: TraceFacade | None = None
    llm: LLMFacade | None = None
    events: EventsFacade | None = None

    # Escape hatch for pack-internal services (domain logic).
    db: Any = None
    services: dict[str, Any] = field(default_factory=dict)

    def require_permission(self, permission: str) -> None:
        """Helper: ``ctx.require_permission("crm.read")``."""
        if self.permissions is None:
            return
        self.permissions.require(permission)


# ---------------------------------------------------------------------------
# Agent base
# ---------------------------------------------------------------------------


class Agent(abc.ABC):
    """Declarative base for a pack agent (sprint 5.4).

    Subclass and declare identity + permissions; implement ``execute(ctx)``.
    No knowledge of the runtime or services is required.
    """

    # Declarative metadata.
    kind: ClassVar[str] = "agent"
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    permissions: ClassVar[list[str]] = []
    tools: ClassVar[list[str]] = []
    model: ClassVar[str | None] = None
    temperature: ClassVar[float | None] = None

    def __init__(self, ctx: AgentContext | None = None) -> None:
        self.ctx = ctx

    @abc.abstractmethod
    def execute(self, ctx: AgentContext) -> AgentOutput:
        """Run the agent against a context. Returns an AgentOutput."""
        raise NotImplementedError

    # --- Introspection ----------------------------------------------------

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "kind": cls.kind,
            "name": cls.name or cls.kind,
            "description": cls.description,
            "permissions": list(cls.permissions),
            "tools": list(cls.tools),
            "model": cls.model,
            "temperature": cls.temperature,
        }


class AgentRegistry:
    """Discovers agent implementations by their declarative ``kind``.

    A pack registers its classes (usually at import time) and the runtime
    resolves agents by kind — the pack never needs a bespoke dispatch table.
    """

    def __init__(self) -> None:
        self._classes: dict[str, type[Agent]] = {}

    def register(self, agent_cls: type[Agent]) -> type[Agent]:
        self._classes[agent_cls.kind] = agent_cls
        return agent_cls

    def get(self, kind: str) -> type[Agent] | None:
        return self._classes.get(kind)

    def require(self, kind: str) -> type[Agent]:
        agent_cls = self.get(kind)
        if agent_cls is None:
            raise KeyError(f"Agent kind {kind!r} не зарегистрирован.")
        return agent_cls

    def kinds(self) -> list[str]:
        return list(self._classes)

    def describe_all(self) -> list[dict[str, Any]]:
        return [cls.describe() for cls in self._classes.values()]


# ---------------------------------------------------------------------------
# Runtime helper
# ---------------------------------------------------------------------------


def run_agent(agent: Agent, ctx: AgentContext) -> AgentOutput:
    """Execute an agent, supporting both sync and async ``execute``."""
    agent.ctx = ctx
    result = agent.execute(ctx)
    if inspect.iscoroutine(result):
        return asyncio.run(result)  # type: ignore[arg-type]
    return result
