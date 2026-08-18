from __future__ import annotations

from typing import Any

from shared.agents import Agent as SDKAgent
from shared.agents import AgentContext, AgentOutput
from sqlalchemy.orm import Session

from app.agents.context import (
    AgentActions,
    AgentApprovals,
    AgentEvents,
    AgentMemory,
    AgentPermissions,
    AgentTools,
    AgentTrace,
)
from app.llm.client import LLMClient
from app.memory.service import MemoryService
from app.models import Agent as AgentRecord
from app.tools.registry import PackToolRegistry


class BaseAgent(SDKAgent):
    """
    Pack-side base for every digital employee (sprint 5.4).

    Subclasses the shared Agent SDK. The pack runtime injects concrete
    services via the legacy constructor, builds an ``AgentContext`` with
    facade implementations, and delegates to the SDK contract ``execute``.
    """

    kind = "base"

    def __init__(
        self,
        record: AgentRecord,
        *,
        memory: MemoryService,
        tools: PackToolRegistry,
        llm: LLMClient,
        db: Session | None = None,
    ) -> None:
        super().__init__(ctx=None)
        self.record = record
        self._memory_service = memory
        self._tools = tools
        self._llm = llm
        self._db = db

    # --- Context construction --------------------------------------------

    def build_context(
        self,
        objective: str,
        input_data: dict[str, Any],
        *,
        task_id: Any = None,
        company_id: Any = None,
    ) -> AgentContext:
        """Wire the SDK facades over the pack services for one run."""
        company_id = company_id or self.record.company_id
        ctx = AgentContext(
            objective=objective,
            input_data=input_data or {},
            agent=self.record,
            agent_id=self.record.id,
            company_id=company_id,
            task_id=task_id,
            memory=AgentMemory(self._memory_service, self.record),
            tools=AgentTools(self._tools),
            actions=AgentActions(self._db, self.record, task_id),
            permissions=AgentPermissions(self.record),
            approvals=AgentApprovals(self._db, self.record, task_id),
            trace=AgentTrace(self._db, self.record),
            llm=self._llm,
            events=AgentEvents(self._db, self.record, task_id),
            db=self._db,
        )
        self.ctx = ctx
        return ctx

    def run(self, ctx: AgentContext) -> AgentOutput:
        """SDK-style entry: agents implement ``execute(ctx)``."""
        return self.execute(ctx)

    # --- Identity (from the database row) ---------------------------------
    # NOTE: instance-level accessors are prefixed with ``record_`` so they
    # never shadow the SDK's declarative ClassVars (``name``, ``tools``, ...).

    @property
    def record_name(self) -> str:
        return self.record.name

    @property
    def record_role(self) -> str:
        return self.record.role

    @property
    def record_goal(self) -> str:
        return self.record.goal

    @property
    def record_slug(self) -> str:
        return self.record.slug

    @property
    def record_tools(self) -> list[str]:
        return [t.tool_name for t in self.record.tools if t.enabled]

    # --- Execution --------------------------------------------------------

    def execute(self, ctx: AgentContext) -> AgentOutput:
        raise NotImplementedError

    # --- Legacy helpers (kept for the existing pack agents) ---------------

    @property
    def memory(self) -> MemoryService:
        return self._memory_service

    @property
    def llm(self) -> LLMClient:
        return self._llm

    @property
    def db(self) -> Session | None:
        return self._db

    def remember(self, content: str, kind: str = "interaction") -> None:
        self._memory_service.remember_short(self.record, content, kind=kind)

    def learn(self, content: str, source_task_id: Any = None) -> None:
        self._memory_service.remember_long(
            self.record, content, source_task_id=source_task_id
        )

    def recall_context(self) -> dict[str, object]:
        return self._memory_service.build_context(self.record)

    # --- Introspection ----------------------------------------------------

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return super().describe()

    def describe_runtime(self) -> dict[str, Any]:
        """Instance-level introspection including the database row."""
        return {
            **self.describe(),
            "id": str(self.record.id),
            "name": self.record_name,
            "slug": self.record_slug,
            "role": self.record_role,
            "goal": self.record_goal,
            "tools": self.record_tools,
            "model": self.record.model,
            "temperature": self.record.temperature,
        }
