from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentAction, LLMUsage, Pack, Task, TaskEvent, User
from app.models.enums import AgentActionStatus


class UsageService:
    """Platform metering (sprint 5.8).

    Counts what the platform can observe without trusting pack-reported
    numbers: LLM tokens/cost, tasks, agent executions, tool calls, workflow
    runs and approval load. Aggregates are attributed at four levels:

    - ``tenant``  — per company
    - ``pack``    — per registered pack
    - ``agent``   — per core agent
    - ``workflow``— per workflow definition (from workflow_runtime events)
    """

    def __init__(self, db: Session):
        self.db = db

    def _window(self, days: int) -> datetime:
        return datetime.now(UTC) - timedelta(days=days)

    def _scoped_llm(self, days: int) -> list[dict[str, Any]]:
        window = self._window(days)
        rows = self.db.execute(
            select(
                LLMUsage.company_id,
                func.count(LLMUsage.id),
                func.coalesce(func.sum(LLMUsage.total_tokens), 0),
                func.coalesce(func.sum(LLMUsage.completion_tokens), 0),
                func.coalesce(func.sum(LLMUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LLMUsage.estimated_cost_rub), 0),
            )
            .where(LLMUsage.created_at >= window)
            .group_by(LLMUsage.company_id)
        ).all()
        return [
            {
                "company_id": str(r[0]) if r[0] else None,
                "llm_calls": r[1],
                "llm_tokens": r[2],
                "llm_completion_tokens": r[3],
                "llm_prompt_tokens": r[4],
                "llm_cost_rub": float(r[5]),
            }
            for r in rows
        ]

    def _scoped_agent_actions(self, days: int) -> list[dict[str, Any]]:
        window = self._window(days)
        rows = self.db.execute(
            select(
                AgentAction.company_id,
                AgentAction.agent_id,
                func.count(AgentAction.id),
            )
            .where(AgentAction.created_at >= window)
            .group_by(AgentAction.company_id, AgentAction.agent_id)
        ).all()
        return [
            {
                "company_id": str(r[0]) if r[0] else None,
                "agent_id": str(r[1]) if r[1] else None,
                "agent_executions": r[2],
            }
            for r in rows
        ]

    def _workflow_runs(self, days: int) -> list[dict[str, Any]]:
        """Count workflow starts per (pack, workflow, company) from
        workflow_runtime events carrying meta attribution (5.8)."""
        window = self._window(days)
        rows = self.db.execute(
            select(TaskEvent.meta, Task.company_id)
            .join(Task, TaskEvent.task_id == Task.id)
            .where(
                TaskEvent.source == "workflow_runtime",
                TaskEvent.created_at >= window,
            )
        ).all()
        result: list[dict[str, Any]] = []
        for meta, company_id in rows:
            if not meta or "workflow" not in meta:
                continue
            result.append(
                {
                    "company_id": str(company_id) if company_id else None,
                    "pack": meta.get("pack"),
                    "workflow": meta.get("workflow"),
                    "workflow_runs": 1,
                }
            )
        return result

    def _approval_counts(self, days: int) -> dict[str, int]:
        window = self._window(days)
        pending = self.db.scalar(
            select(func.count(AgentAction.id)).where(
                AgentAction.created_at >= window,
                AgentAction.requires_approval.is_(True),
                AgentAction.status == AgentActionStatus.pending,
            )
        ) or 0
        decided = self.db.scalar(
            select(func.count(AgentAction.id)).where(
                AgentAction.created_at >= window,
                AgentAction.requires_approval.is_(True),
                AgentAction.status.in_(
                    [AgentActionStatus.executed, AgentActionStatus.cancelled]
                ),
            )
        ) or 0
        return {"approvals_pending": pending, "approvals_decided": decided}

    def _task_counts(self, days: int, scope: uuid.UUID | None = None) -> dict[str, int]:
        window = self._window(days)
        total = self.db.scalar(
            select(func.count(Task.id)).where(Task.created_at >= window)
        ) or 0
        completed = self.db.scalar(
            select(func.count(Task.id)).where(
                Task.created_at >= window, Task.status == "completed"
            )
        ) or 0
        failed = self.db.scalar(
            select(func.count(Task.id)).where(
                Task.created_at >= window, Task.status == "failed"
            )
        ) or 0
        if scope is not None:
            total = self.db.scalar(
                select(func.count(Task.id)).where(
                    Task.created_at >= window, Task.company_id == scope
                )
            ) or 0
            completed = self.db.scalar(
                select(func.count(Task.id)).where(
                    Task.created_at >= window,
                    Task.company_id == scope,
                    Task.status == "completed",
                )
            ) or 0
            failed = self.db.scalar(
                select(func.count(Task.id)).where(
                    Task.created_at >= window,
                    Task.company_id == scope,
                    Task.status == "failed",
                )
            ) or 0
        return {
            "tasks_total": total,
            "tasks_completed": completed,
            "tasks_failed": failed,
        }

    def _storage_rows(self) -> dict[str, int]:
        """Approximate stored rows per core table (a proxy for storage)."""
        counts: dict[str, int] = {}
        for model in (Task, TaskEvent, AgentAction, LLMUsage):
            counts[model.__tablename__] = (
                self.db.scalar(select(func.count()).select_from(model)) or 0
            )
        return counts

    def _tool_calls(self, days: int) -> int:
        """Tool calls = executed agent actions that are not human checkpoints."""
        window = self._window(days)
        return self.db.scalar(
            select(func.count(AgentAction.id)).where(
                AgentAction.created_at >= window,
                AgentAction.status == AgentActionStatus.executed,
                AgentAction.action_type != "workflow_human",
            )
        ) or 0

    def summary(self, days: int = 30, scope: uuid.UUID | None = None) -> dict[str, Any]:
        llm = self._scoped_llm(days)
        actions = self._scoped_agent_actions(days)
        runs = self._workflow_runs(days)
        approvals = self._approval_counts(days)
        tasks = self._task_counts(days, scope)

        by_tenant: dict[str, dict[str, Any]] = {}
        for row in llm:
            key = row["company_id"] or "unknown"
            bucket = by_tenant.setdefault(
                key,
                {
                    "tenant": key,
                    "llm_calls": 0,
                    "llm_tokens": 0,
                    "llm_cost_rub": 0.0,
                    "agent_executions": 0,
                    "workflow_runs": 0,
                },
            )
            bucket["llm_calls"] += row["llm_calls"]
            bucket["llm_tokens"] += row["llm_tokens"]
            bucket["llm_cost_rub"] += row["llm_cost_rub"]
        for row in actions:
            key = row["company_id"] or "unknown"
            bucket = by_tenant.setdefault(
                key,
                {
                    "tenant": key,
                    "llm_calls": 0,
                    "llm_tokens": 0,
                    "llm_cost_rub": 0.0,
                    "agent_executions": 0,
                    "workflow_runs": 0,
                },
            )
            bucket["agent_executions"] += row["agent_executions"]
        for row in runs:
            key = row["company_id"] or "unknown"
            bucket = by_tenant.setdefault(
                key,
                {
                    "tenant": key,
                    "llm_calls": 0,
                    "llm_tokens": 0,
                    "llm_cost_rub": 0.0,
                    "agent_executions": 0,
                    "workflow_runs": 0,
                },
            )
            bucket["workflow_runs"] += row["workflow_runs"]
        if scope is not None:
            by_tenant = {k: v for k, v in by_tenant.items() if k == str(scope)}

        by_pack: dict[str, dict[str, Any]] = {}
        for row in runs:
            pack = row["pack"] or "unknown"
            bucket = by_pack.setdefault(pack, {"pack": pack, "workflow_runs": 0})
            bucket["workflow_runs"] += row["workflow_runs"]

        by_workflow: dict[str, dict[str, Any]] = {}
        for row in runs:
            name = row["workflow"] or "unknown"
            bucket = by_workflow.setdefault(name, {"workflow": name, "workflow_runs": 0})
            bucket["workflow_runs"] += row["workflow_runs"]

        by_agent: dict[str, dict[str, Any]] = {}
        for row in actions:
            if not row["agent_id"]:
                continue
            bucket = by_agent.setdefault(
                row["agent_id"], {"agent_id": row["agent_id"], "agent_executions": 0}
            )
            bucket["agent_executions"] += row["agent_executions"]

        packs = self.db.scalars(select(Pack).order_by(Pack.name)).all()
        by_pack = {
            name: {
                **bucket,
                "version": next((p.version for p in packs if p.name == name), None),
                "is_active": next((p.is_active for p in packs if p.name == name), False),
            }
            for name, bucket in by_pack.items()
        }

        total_llm_cost = round(sum(v["llm_cost_rub"] for v in by_tenant.values()), 4)
        return {
            "days": days,
            "totals": {
                **tasks,
                **approvals,
                "llm_calls": sum(v.get("llm_calls", 0) for v in by_tenant.values()),
                "llm_tokens": sum(v.get("llm_tokens", 0) for v in by_tenant.values()),
                "llm_cost_rub": total_llm_cost,
                "agent_executions": sum(
                    v.get("agent_executions", 0) for v in by_tenant.values()
                ),
                "tool_calls": self._tool_calls(days),
                "workflow_runs": sum(v["workflow_runs"] for v in by_pack.values()),
            },
            "by_tenant": sorted(by_tenant.values(), key=lambda v: -v.get("llm_cost_rub", 0)),
            "by_pack": sorted(by_pack.values(), key=lambda v: -v["workflow_runs"]),
            "by_workflow": sorted(
                by_workflow.values(), key=lambda v: -v["workflow_runs"]
            ),
            "by_agent": sorted(by_agent.values(), key=lambda v: -v["agent_executions"]),
            "storage_rows": self._storage_rows(),
        }

    @staticmethod
    def user_scope(user: User) -> uuid.UUID | None:
        return user.company_id
