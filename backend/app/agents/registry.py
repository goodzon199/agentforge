from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.system import SystemAgent

_AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "system": SystemAgent,
}


class AgentRegistry:
    """Maps agent types/kinds to their Python implementations."""

    def get_class(self, agent_type: str) -> type[BaseAgent]:
        return _AGENT_CLASSES.get(agent_type, BaseAgent)

    def kinds(self) -> list[str]:
        return list(_AGENT_CLASSES.keys())


agent_registry = AgentRegistry()
