from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.client import LLMClient
from app.memory.service import MemoryService
from app.models import Agent as AgentRecord
from app.tools.registry import ToolRegistry


@dataclass
class AgentOutput:
    response: str
    data: dict[str, Any] = field(default_factory=dict)
    routing_decision: dict[str, Any] = field(default_factory=dict)
    handoff_agent: str | None = None


class BaseAgent:
    """
    Contract every digital employee implements.

    An agent is a live object with identity (name, role, goal), a behaviour
    contract (instructions), capabilities (tools + permissions), a model
    configuration, memory, and statistics.
    """

    kind: str = "base"

    def __init__(
        self,
        record: AgentRecord,
        *,
        memory: MemoryService,
        tools: ToolRegistry,
        llm: LLMClient,
    ) -> None:
        self.record = record
        self.memory = memory
        self.tools = tools
        self.llm = llm

    # --- Identity (from the database row) ---------------------------------

    @property
    def name(self) -> str:
        return self.record.name

    @property
    def role(self) -> str:
        return self.record.role

    @property
    def goal(self) -> str:
        return self.record.goal

    @property
    def slug(self) -> str:
        return self.record.slug

    @property
    def available_tools(self) -> list[str]:
        return [t.tool_name for t in self.record.tools if t.enabled]

    # --- Execution --------------------------------------------------------

    def execute(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        raise NotImplementedError

    # --- Memory helpers ---------------------------------------------------

    def remember(self, content: str, kind: str = "interaction") -> None:
        self.memory.remember_short(self.record, content, kind=kind)

    def learn(self, content: str, source_task_id: Any = None) -> None:
        self.memory.remember_long(
            self.record, content, source_task_id=source_task_id
        )

    def recall_context(self) -> dict[str, object]:
        return self.memory.build_context(self.record)

    # --- Introspection ----------------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "id": str(self.record.id),
            "name": self.name,
            "slug": self.slug,
            "role": self.role,
            "goal": self.goal,
            "tools": self.available_tools,
            "model": self.record.model,
            "temperature": self.record.temperature,
        }
