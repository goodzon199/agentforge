from __future__ import annotations

from shared.agents import AgentRegistry as SDKAgentRegistry

from app.agents.base import BaseAgent
from app.agents.email import EmailAgent
from app.agents.intake_agent import IntakeAgent
from app.agents.pricing import PricingAgent
from app.agents.sales import SalesAgent
from app.agents.search import SearchAgent
from app.agents.system import SystemAgent

# Map SystemAgent handoff names to agent types/slugs.
HANDOFF_TO_TYPE: dict[str, str] = {
    "EmailAgent": "email",
    "SearchAgent": "search",
    "IntakeAgent": "intake",
    "PricingAgent": "pricing",
    "SalesAgent": "sales",
}


class AgentRegistry(SDKAgentRegistry):
    """Pack registry over the shared Agent SDK (sprint 5.4).

    Registers the pack's agent classes so both the shared ``describe_all``
    introspection and the legacy ``get_class`` constructor-based dispatch
    work for the existing pack agents.
    """

    def __init__(self) -> None:
        super().__init__()
        for cls in (
            SystemAgent,
            EmailAgent,
            SearchAgent,
            IntakeAgent,
            PricingAgent,
            SalesAgent,
        ):
            self.register(cls)

    def get_class(self, agent_type: str) -> type[BaseAgent]:
        return self.get(agent_type) or BaseAgent

    def resolve_handoff(self, handoff_agent: str | None) -> str | None:
        """Return the agent type for a handoff name, or None if unavailable."""
        if not handoff_agent:
            return None
        return HANDOFF_TO_TYPE.get(handoff_agent)


agent_registry = AgentRegistry()
