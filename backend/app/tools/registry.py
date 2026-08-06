from __future__ import annotations

from typing import Any

from app.tools.base import BaseTool, ToolResult
from app.tools.builtin.email_tool import EmailTool
from app.tools.builtin.http_tool import HttpTool
from app.tools.builtin.search_tool import SearchTool


class ToolRegistry:
    """Central registry of every tool module available to agents."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        for tool in (SearchTool(), EmailTool(), HttpTool()):
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def run(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        return tool.run(**kwargs)

    def list(self) -> list[dict[str, Any]]:
        return [tool.describe() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())


tool_registry = ToolRegistry()
