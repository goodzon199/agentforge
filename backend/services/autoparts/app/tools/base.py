"""Pack tool layer built on the shared Tool SDK (sprint 5.4).

``BaseTool`` / ``ToolResult`` / ``ToolRegistry`` are the shared SDK contracts.
Autoparts only adds its own tool implementations and a traced ``run``.
"""

from __future__ import annotations

from shared.tools import Tool as BaseTool
from shared.tools import ToolRegistry, ToolResult

__all__ = ["BaseTool", "ToolRegistry", "ToolResult"]
