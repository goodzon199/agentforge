from __future__ import annotations

from typing import Any

from app.tools.base import ToolRegistry, ToolResult
from app.tools.builtin.email_tool import EmailTool
from app.tools.builtin.http_tool import HttpTool
from app.tools.builtin.search_tool import SearchTool


class PackToolRegistry(ToolRegistry):
    """Autoparts tool registry: shared SDK registry + distributed tracing.

    Agents reach tools through ``ctx.tools``; every run is wrapped in a
    ``tool`` span so tool usage is visible in the trace.
    """

    def run(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        from app.tracing.tracer import current_db, trace

        db = current_db()
        if db is not None:
            with trace(
                db,
                "tool",
                f"tool.{name}",
                metadata={"kwargs_keys": sorted(kwargs.keys())},
            ):
                return tool.run(**kwargs)
        return tool.run(**kwargs)


def build_pack_tool_registry() -> PackToolRegistry:
    registry = PackToolRegistry()
    for tool in (SearchTool(), EmailTool(), HttpTool()):
        registry.register(tool)
    return registry


tool_registry = build_pack_tool_registry()
