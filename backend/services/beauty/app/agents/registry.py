"""Agent registry for the Beauty pack (sprint 5.5).

Pure-SDK ``AgentRegistry``: agents resolve by their declarative ``kind``,
exactly matching the manifest agent types. No bespoke dispatch table.
"""

from __future__ import annotations

from shared.agents import AgentRegistry

from app.agents.base import BeautyAgent
from app.agents.booking import BookingAgent
from app.agents.calendar_agent import CalendarAgent
from app.agents.reception import ReceptionAgent
from app.agents.reminder import ReminderAgent
from app.agents.sales import SalesAgent

agent_registry = AgentRegistry()
for _cls in (
    ReceptionAgent,
    CalendarAgent,
    BookingAgent,
    SalesAgent,
    ReminderAgent,
):
    agent_registry.register(_cls)


def get_class(kind: str) -> type[BeautyAgent]:
    cls = agent_registry.get(kind)
    if cls is None:
        raise KeyError(f"Agent kind {kind!r} не зарегистрирован.")
    return cls  # type: ignore[return-value]
