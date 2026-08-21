"""Tool SDK (sprint 5.4).

A pack developer writes a tool declaratively, without knowing how the pack
registers or executes tools:

    from shared.tools import Tool, ToolResult, ToolRegistry

    class CrmWriteTool(Tool):
        name = "crm.write_lead"
        description = "Create or update a CRM lead."
        permissions = ["crm.write"]

        def run(self, **kwargs) -> ToolResult:
            ...

Pure Python (pydantic only). The pack runtime owns the registry instance and
injects concrete tools; agents call ``ctx.tools.run(name, **kwargs)``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel


class ToolResult(BaseModel):
    """Result of a tool run."""

    ok: bool = True
    data: Any = None
    error: str | None = None


class Tool(ABC):
    """Declarative base for a pack tool (sprint 5.4)."""

    name: ClassVar[str] = "tool"
    description: ClassVar[str] = ""
    input_schema: ClassVar[dict[str, Any]] = {}
    version: ClassVar[str] = "1.0.0"
    permissions: ClassVar[list[str]] = []

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with validated keyword arguments."""
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "input_schema": self.input_schema,
            "permissions": list(self.permissions),
        }


class ToolRegistry:
    """Central registry of tools available to agents.

    The pack registers its tools; agents reach them through ``ctx.tools``.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def run(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"Unknown tool: {name}")
        return tool.run(**kwargs)

    def names(self) -> list[str]:
        return list(self._tools)

    def list(self) -> list[dict[str, Any]]:
        return [tool.describe() for tool in self._tools.values()]
