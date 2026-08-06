from __future__ import annotations

from typing import Any

from app.tools.base import BaseTool, ToolResult


class HttpTool(BaseTool):
    """
    Generic HTTP request tool. Stub contract for calling external REST APIs.
    """

    name = "http"
    description = "Perform an HTTP request (GET/POST) to a configured external API."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string", "enum": ["GET", "POST"]},
            "headers": {"type": "object"},
            "body": {"type": "object"},
        },
        "required": ["url", "method"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            ok=True,
            data={
                "handoff_required": True,
                "handoff_agent": None,
                "url": kwargs.get("url"),
                "message": "HTTP tool requires an allow-listed provider configuration.",
            },
        )
