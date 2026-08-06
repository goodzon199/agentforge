from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.registry import agent_registry
from app.core.redis import redis_client
from app.llm.client import LLMClient, llm_client
from app.memory.service import MemoryService
from app.models import Agent as AgentRecord
from app.models import Task, TaskEvent
from app.models.enums import TaskStatus
from app.orchestrator.messages import ResultMessage, TaskMessage
from app.tools.registry import ToolRegistry, tool_registry

logger = logging.getLogger(__name__)

# Name of the platform's built-in dispatcher agent.
SYSTEM_AGENT_SLUG = "system-agent"


class Orchestrator:
    """
    The heart of the platform.

    Responsibilities:
      * accept tasks and enqueue them (Redis queue when available)
      * route each task to the right agent implementation
      * execute agent logic, record events/logs and statistics
      * scale to many agents/workers (queue-based by design)
    """

    def __init__(
        self,
        *,
        tools: ToolRegistry = tool_registry,
        llm: LLMClient = llm_client,
    ) -> None:
        self.tools = tools
        self.llm = llm
        self._workers: list[Any] = []

    # --- Public API -------------------------------------------------------

    def submit(self, db: Session, task: Task) -> Task:
        """Queue the task and process it. Returns the updated task.

        If Redis is available the task is queued for the worker pool;
        otherwise it is processed inline (synchronous mode).
        """
        if redis_client.available:
            task.status = TaskStatus.queued
            db.add(
                TaskEvent(
                    task_id=task.id,
                    source="orchestrator",
                    level="info",
                    message="Задача поставлена в очередь.",
                )
            )
            db.commit()
            message = TaskMessage(
                task_id=task.id,
                company_id=task.company_id,
                objective=task.objective,
                input_data=task.input_data or {},
                priority=task.priority.value,
            )
            redis_client.push("agentos:tasks", message.to_dict())
            return task

        # Synchronous fallback: process inline.
        self.process(db, task)
        return task

    def process(self, db: Session, task: Task) -> Task:
        """Execute one task against the agent pipeline.

        Flow: SystemAgent routes the task; if it hands off to a specialized
        agent (e.g. EmailAgent), the task is dispatched to that agent and
        the final answer comes from it.
        """
        task.status = TaskStatus.running
        task.started_at = _now()
        db.commit()

        try:
            agent_record = self._resolve_system_agent(db)
            if agent_record is None:
                raise RuntimeError("SystemAgent не найден в базе.")

            system = agent_registry.get_class("system")(
                record=agent_record,
                memory=MemoryService(db),
                tools=self.tools,
                llm=self.llm,
            )

            self._add_event(
                db,
                task,
                source=f"agents.{system.slug}",
                message=f"Агент {system.name} получил задачу.",
            )

            decision = system.execute(task.objective, task.input_data or {})
            system.remember(
                f"Задача: {task.objective} -> маршрут: {decision.routing_decision}",
                kind="routing",
            )

            # Hand off to a specialized agent when SystemAgent determined one.
            handoff_type = agent_registry.resolve_handoff(decision.handoff_agent)
            if handoff_type:
                target_record = self._resolve_agent_by_type(db, handoff_type)
                if target_record is None:
                    raise RuntimeError(
                        f"Агент для {decision.handoff_agent} не найден в базе."
                    )
                self._add_event(
                    db,
                    task,
                    source="orchestrator",
                    message=f"SystemAgent передал задачу агенту {target_record.name}.",
                )

                target = agent_registry.get_class(handoff_type)(
                    record=target_record,
                    memory=MemoryService(db),
                    tools=self.tools,
                    llm=self.llm,
                )
                output = target.execute(task.objective, task.input_data or {})
                target.remember(
                    f"Задача: {task.objective} -> {output.response}",
                    kind="task_result",
                )
                final_agent = target_record
            else:
                output = decision
                final_agent = agent_record
                system.remember(
                    f"Задача: {task.objective} -> {output.response}",
                    kind="task_result",
                )

            task.output_data = {
                "response": output.response,
                "data": output.data,
                "handoff_agent": output.handoff_agent,
            }
            task.routing_decision = output.routing_decision
            task.status = TaskStatus.completed
            task.completed_at = _now()

            self._add_event(
                db,
                task,
                source="orchestrator",
                message=f"Задача завершена. {output.response}",
            )
            self._update_statistics(db, final_agent, success=True)
            db.commit()
            return task

        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Task %s failed", task.id)
            task.status = TaskStatus.failed
            task.error = str(exc)
            task.completed_at = _now()
            self._add_event(
                db,
                task,
                source="orchestrator",
                level="error",
                message=f"Ошибка выполнения: {exc}",
            )
            db.commit()
            return task

    # --- Queue worker support --------------------------------------------

    def poll(self, db: Session) -> None:
        """Consume a single queued message (blocking up to 1s)."""
        raw = redis_client.pop("agentos:tasks")
        if raw is None:
            return
        message = TaskMessage.from_dict(raw)
        task = db.get(Task, message.task_id)
        if task is not None:
            self.process(db, task)

    # --- Internals --------------------------------------------------------

    def _resolve_system_agent(self, db: Session) -> AgentRecord | None:
        stmt = select(AgentRecord).where(AgentRecord.slug == SYSTEM_AGENT_SLUG)
        return db.scalars(stmt).first()

    def _resolve_agent_by_type(self, db: Session, agent_type: str) -> AgentRecord | None:
        """Resolve an agent record by its type slug convention (e.g. email -> email-agent)."""
        stmt = select(AgentRecord).where(AgentRecord.slug == f"{agent_type}-agent")
        return db.scalars(stmt).first()

    def _add_event(
        self,
        db: Session,
        task: Task,
        source: str,
        message: str,
        level: str = "info",
        meta: dict[str, Any] | None = None,
    ) -> None:
        db.add(
            TaskEvent(
                task_id=task.id,
                agent_id=task.agent_id,
                source=source,
                level=level,
                message=message,
                meta=meta or {},
            )
        )

    def _update_statistics(self, db: Session, agent: AgentRecord, *, success: bool) -> None:
        agent.tasks_total += 1
        if success:
            agent.tasks_completed += 1
        else:
            agent.tasks_failed += 1
        agent.avg_success_rate = round(
            (agent.tasks_completed / agent.tasks_total) * 100 if agent.tasks_total else 0.0,
            2,
        )


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


orchestrator = Orchestrator()
