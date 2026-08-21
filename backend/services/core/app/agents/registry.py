from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.email import EmailAgent
from app.agents.system import SystemAgent

_AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "system": SystemAgent,
    "email": EmailAgent,
}

# Map SystemAgent handoff names to agent types/slugs. Domain agents are
# recognized for routing but executed REMOTELY in the autoparts service over
# the internal contract (sprint 5.0): core never imports their implementations.
HANDOFF_TO_TYPE: dict[str, str] = {
    "EmailAgent": "email",
    "SearchAgent": "search",
    "IntakeAgent": "intake",
    "PricingAgent": "pricing",
    "SalesAgent": "sales",
}

# Agent types whose execution lives in the autoparts service.
REMOTE_AGENT_TYPES = frozenset({"search", "intake", "pricing", "sales"})


class AgentRegistry:
    """Maps agent types/kinds to their Python implementations."""

    def get_class(self, agent_type: str) -> type[BaseAgent]:
        return _AGENT_CLASSES.get(agent_type, BaseAgent)

    def resolve_handoff(self, handoff_agent: str | None) -> str | None:
        """Return the agent type for a handoff name, or None if unavailable."""
        if not handoff_agent:
            return None
        return HANDOFF_TO_TYPE.get(handoff_agent)

    def kinds(self) -> list[str]:
        return list(_AGENT_CLASSES.keys())

    def is_remote(self, agent_type: str) -> bool:
        """True when the agent executes in the autoparts service."""
        return agent_type in REMOTE_AGENT_TYPES


agent_registry = AgentRegistry()
