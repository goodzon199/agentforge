from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    ok: bool = True
    data: Any = None
    error: str | None = None


class BaseTool(ABC):
    """Every tool is an isolated module. Agents only call `run()`.

    A tool knows nothing about agents; it exposes a contract
    (name, description, input schema) so the orchestrator and
    agents can route to it generically.
    """

    name: str = "base"
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    version: str = "1.0.0"

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
        }
