from __future__ import annotations

import logging
import time
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.registry import agent_registry
from app.core.config import settings
from app.core.emergency import emergency_switch
from app.core.redis import redis_client
from app.llm.client import LLMClient, TaskLLMProxy, llm_client
from app.memory.service import MemoryService
from app.models import Agent as AgentRecord
from app.models import Task, TaskEvent, Trace
from app.models.enums import TaskStatus
from app.orchestrator.messages import TaskMessage
from app.reliability.errors import TRANSIENT, FailureKind, classify_exception
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

        # Wrap the shared LLM client per task so token usage can be attributed
        # to the executing agent (cost/task metric, sprint 3.2).
        llm = TaskLLMProxy(self.llm)

        # Distributed tracing (sprint 3.6): every task joins its trace. Tasks
        # created from a customer message already carry a trace_id (set in
        # ConversationService.add_message); ad-hoc API tasks get a fresh trace.
        from app.tracing.tracer import (
            bind_db,
            maybe_finish_trace,
            resolve_trace_for_conversation,
            trace,
            unbind_db,
        )

        task_span_parent: Any = None
        if task.trace_id is None:
            conversation_id = (task.input_data or {}).get("conversation_id")
            task.trace_id = resolve_trace_for_conversation(
                db,
                _as_uuid(conversation_id),
                company_id=task.company_id,
                source="manual_task",
            )
            db.commit()
            # resolve_trace_for_conversation opened a fresh trace: nest the
            # task span under its root conversation span.
            fresh = db.get(Trace, task.trace_id)
            task_span_parent = fresh.root_span_id if fresh else None
        else:
            # The worker context has no active span stack (the trace was
            # opened by the API request that created the task), so the task
            # span must attach to the trace's root span explicitly.
            existing = db.get(Trace, task.trace_id)
            task_span_parent = existing.root_span_id if existing else None

        db_token = bind_db(db)
        try:
            with trace(
                db,
                "task",
                task.title,
                trace_id=task.trace_id,
                parent_span_id=task_span_parent,
                task_id=task.id,
                metadata={"objective": task.objective},
            ):
                return self._run_pipeline(db, task, llm)
        finally:
            unbind_db(db_token)
            maybe_finish_trace(db, task.trace_id)
            db.commit()

    def _run_pipeline(self, db: Session, task: Task, llm: TaskLLMProxy) -> Task:
        from app.tracing.tracer import trace

        try:
            agent_record = self._resolve_system_agent(db)
            if agent_record is None:
                raise RuntimeError("SystemAgent не найден в базе.")

            system = agent_registry.get_class("system")(
                record=agent_record,
                memory=MemoryService(db),
                tools=self.tools,
                llm=llm,
                db=db,
            )

            self._add_event(
                db,
                task,
                source=f"agents.{system.slug}",
                message=f"Агент {system.name} получил задачу.",
            )

            with trace(
                db,
                "agent",
                f"{system.name} ({system.slug})",
                task_id=task.id,
                agent_id=agent_record.id,
                metadata={"kind": getattr(system, "kind", system.slug)},
            ):
                decision = system.execute(task.objective, task.input_data or {})
            system.remember(
                f"Задача: {task.objective} -> маршрут: {decision.routing_decision}",
                kind="routing",
            )

            # Hand off to a specialized agent when SystemAgent determined one.
            handoff_type = agent_registry.resolve_handoff(decision.handoff_agent)
            if handoff_type:
                if agent_registry.is_remote(handoff_type):
                    # Sprint 5.0: domain agents live in autoparts. Dispatch over
                    # the internal contract; the task completes with the remote
                    # output, attributed to the domain agent (resolved locally
                    # by slug so the audit/task record stays consistent).
                    target_record = self._resolve_agent_by_type(db, handoff_type)
                    if target_record is None:
                        raise RuntimeError(
                            f"Агент для {decision.handoff_agent} не найден в базе."
                        )
                    self._add_event(
                        db,
                        task,
                        source="orchestrator",
                        message=(
                            f"SystemAgent передал задачу агенту {target_record.name} "
                            "(autoparts-service, internal contract)."
                        ),
                    )
                    output = self._dispatch_remote(
                        db, task, handoff_type, target_record
                    )
                    final_agent = target_record
                else:
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
                        llm=llm,
                        db=db,
                    )
                    with trace(
                        db,
                        "agent",
                        f"{target_record.name} ({getattr(target, 'kind', target.slug)})",
                        task_id=task.id,
                        agent_id=target_record.id,
                        metadata={"kind": getattr(target, "kind", target.slug)},
                    ):
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
            task.error = None
            task.completed_at = _now()
            # Attribute the task to the agent that actually executed it.
            task.agent_id = final_agent.id

            self._add_event(
                db,
                task,
                source="orchestrator",
                message=f"Задача завершена. {output.response}",
            )
            llm.flush(
                db,
                task_id=task.id,
                company_id=task.company_id,
                agent_id=final_agent.id,
            )
            self._update_statistics(db, final_agent, success=True)
            db.commit()
            return task

        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Task %s failed", task.id)
            kind = classify_exception(exc)
            llm.flush(db, task_id=task.id, company_id=task.company_id)

            # Transient failures requeue (bounded); everything else goes to
            # the dead-letter queue. Business errors are never retried.
            if kind in TRANSIENT and task.retries < settings.task_max_retries:
                task.retries += 1
                task.status = TaskStatus.queued
                task.started_at = None
                task.completed_at = None
                task.error = (
                    f"retry {task.retries}/{settings.task_max_retries} "
                    f"({kind.value}): {exc}"
                )
                self._add_event(
                    db,
                    task,
                    source="orchestrator",
                    level="warning",
                    message=(
                        f"Транзиентная ошибка ({kind.value}), повтор "
                        f"{task.retries}/{settings.task_max_retries}: {exc}"
                    ),
                    meta={"kind": kind.value, "attempt": task.retries},
                )
                db.commit()
                if redis_client.available:
                    redis_client.push(
                        settings.task_queue_name,
                        TaskMessage(
                            task_id=task.id,
                            company_id=task.company_id,
                            objective=task.objective,
                            input_data=task.input_data or {},
                            priority=task.priority.value,
                        ).to_dict(),
                    )
                else:
                    self.process(db, task)  # inline re-run (Redis fallback)
                return task

            task.status = TaskStatus.failed
            task.error = str(exc)
            task.completed_at = _now()
            self._add_event(
                db,
                task,
                source="orchestrator",
                level="error",
                message=f"Ошибка выполнения ({kind.value}): {exc}",
                meta={"kind": kind.value},
            )
            self._dead_letter(db, task, kind)
            db.commit()
            return task

    # --- Queue worker support --------------------------------------------

    def poll(self, db: Session) -> None:
        """Consume a single queued message (blocking up to 1s)."""
        raw = redis_client.pop("agentos:tasks")
        if raw is None:
            return
        if emergency_switch.is_engaged():
            # Global pause: leave the message in the queue untouched and idle.
            # The task is processed later when the switch is released.
            redis_client.push_raw("agentos:tasks", raw)
            time.sleep(1.0)
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

    def _dispatch_remote(
        self,
        db: Session,
        task: Task,
        agent_type: str,
        agent_record: AgentRecord,
    ):
        """Dispatch a domain task to the autoparts service (sprint 5.0).

        POST /internal/agents/execute with the task objective/input_data; the
        domain service runs its own agent implementation and returns the
        output. The internal client raises on transport/HTTP errors, which the
        task pipeline classifies (transient retry or dead-letter).
        """
        from shared.internal import internal_post

        from app.core.config import settings
        from app.tracing.tracer import trace

        try:
            result = internal_post(
                settings.autoparts_internal_url,
                "/internal/agents/execute",
                payload={
                    "agent_type": agent_type,
                    "objective": task.objective,
                    "input_data": task.input_data or {},
                },
                timeout=settings.llm_read_timeout + 10.0,
            )
        except Exception as exc:  # pragma: no cover - network error path
            logger.warning(
                "Remote dispatch to autoparts failed for task %s: %s",
                task.id,
                exc,
            )
            raise

        class _RemoteOutput:
            def __init__(self, data: dict) -> None:
                self.response = data.get("response", "")
                self.data = data.get("data", {})
                self.handoff_agent = data.get("handoff_agent")
                self.routing_decision = data.get("routing_decision")

        with trace(
            db,
            "agent",
            f"{agent_record.name} ({agent_type}, remote)",
            task_id=task.id,
            agent_id=agent_record.id,
            metadata={"kind": agent_type, "remote": True},
        ):
            pass
        return _RemoteOutput(result)

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

    def _dead_letter(
        self, db: Session, task: Task, kind: FailureKind
    ) -> None:
        """Move a failed task to the dead-letter queue.

        Postgres (``dead_tasks``) is the source of truth; the Redis
        ``agentos:tasks:dead`` list is only a fast signal for operators.
        """
        from app.models import DeadTask

        attempts = task.retries + 1
        db.add(
            DeadTask(
                task_id=task.id,
                company_id=task.company_id,
                agent_id=task.agent_id,
                objective=task.objective,
                payload=task.input_data or {},
                exception_kind=kind.value,
                error=task.error,
                attempts=attempts,
                dead_at=_now(),
            )
        )
        redis_client.push(
            settings.dlq_queue_name,
            {
                "task_id": str(task.id),
                "exception_kind": kind.value,
                "attempts": attempts,
                "dead_at": _now().isoformat(),
            },
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
        # total_llm_calls is derived from LLMUsage (the single source of truth),
        # not incremented by hand. Setting (not +=) keeps a re-processed task
        # from inflating the counter.
        from sqlalchemy import func

        from app.models import LLMUsage

        db.flush()  # make the just-flushed usage rows visible to the count
        count = db.scalar(
            select(func.count())
            .select_from(LLMUsage)
            .where(LLMUsage.agent_id == agent.id)
        )
        agent.total_llm_calls = int(count or 0)


def _now():
    from datetime import datetime

    return datetime.now(UTC)


def _as_uuid(value: Any) -> Any:
    """Coerce a string UUID to uuid.UUID (tolerates None/invalid)."""
    import uuid

    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


orchestrator = Orchestrator()
