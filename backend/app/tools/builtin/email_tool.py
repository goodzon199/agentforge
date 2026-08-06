from __future__ import annotations

from typing import Any

from app.tools.base import BaseTool, ToolResult


class EmailTool(BaseTool):
    """Contract stub for sending e-mail. Needs a provider in a later sprint."""

    name = "email"
    description = "Send an e-mail to a recipient. Requires a configured e-mail provider."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            ok=True,
            data={
                "handoff_required": True,
                "handoff_agent": "EmailAgent",
                "to": kwargs.get("to"),
                "subject": kwargs.get("subject"),
            },
        )
