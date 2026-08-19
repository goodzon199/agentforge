"""Base for Beauty agents (sprint 5.5).

Subclasses the shared Agent SDK directly — no DB record, no pack internals.
The runtime builds an ``AgentContext`` with pure-SDK facades and delegates to
the SDK contract ``execute(ctx)``.
"""

from __future__ import annotations

from typing import Any

from shared.agents import Agent as SDKAgent
from shared.agents import AgentContext

from app.context import NoopTrace, RunAudit, RunMemory, RunPermissions


class BeautyAgent(SDKAgent):
    """SDK Agent + context construction for the Beauty pack."""

    kind = "beauty"

    def build_context(
        self,
        objective: str,
        input_data: dict[str, Any],
        *,
        task_id: Any = None,
        company_id: Any = None,
    ) -> AgentContext:
        """Wire the pure-SDK facades for one run."""
        from shared.tools import ToolRegistry

        from app.tools.registry import tool_registry

        tools = ToolRegistry()
        for name in tool_registry.names():
            tool = tool_registry.get(name)
            if tool is not None:
                tools.register(tool)
        memory = RunMemory()
        audit = RunAudit()
        ctx = AgentContext(
            objective=objective,
            input_data=input_data or {},
            agent_id=self.kind,
            company_id=company_id,
            task_id=task_id,
            memory=memory,
            tools=tools,
            actions=audit,
            permissions=RunPermissions(),
            approvals=audit,
            trace=NoopTrace(),
            events=audit,
        )
        self.ctx = ctx
        return ctx

    def run(self, ctx: AgentContext):
        return self.execute(ctx)
