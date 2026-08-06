from __future__ import annotations

from typing import Any

from app.tools.base import BaseTool, ToolResult


class SearchTool(BaseTool):
    """
    Search provider tool. In Sprint 1 it is a contract stub: it defines the
    input/output shape (query, filters, limit) and returns a clear signal
    that the actual provider (web / parts / e-commerce) is not connected yet.
    """

    name = "search"
    description = (
        "Search for information, products, articles or parts by natural-language query. "
        "Requires a configured search provider (SearchAgent)."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "filters": {"type": "object"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    }

    def run(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        return ToolResult(
            ok=True,
            data={
                "handoff_required": True,
                "handoff_agent": "SearchAgent",
                "query": query,
                "message": "Search provider is not configured yet. For execution a SearchAgent is required.",
            },
        )
