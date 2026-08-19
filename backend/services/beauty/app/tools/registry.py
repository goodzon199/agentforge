"""Tool registry for the Beauty pack (sprint 5.5).

Built on the shared Tool SDK: registers the pack's tools into a
``ToolRegistry``. Agents reach them through ``ctx.tools``.
"""

from __future__ import annotations

from shared.tools import ToolRegistry

from app.tools.salon_tools import (
    CalendarBookTool,
    CalendarSlotsTool,
    ReminderScheduleTool,
    SalonCatalogTool,
)

_tool_registry = ToolRegistry()


def build_tool_registry() -> ToolRegistry:
    for tool in (
        SalonCatalogTool(),
        CalendarSlotsTool(),
        CalendarBookTool(),
        ReminderScheduleTool(),
    ):
        _tool_registry.register(tool)
    return _tool_registry


tool_registry = build_tool_registry()
