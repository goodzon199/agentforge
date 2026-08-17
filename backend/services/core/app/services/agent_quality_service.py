from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Agent,
    AgentAction,
    AgentFeedback,
    LLMUsage,
    Task,
)
from app.models.enums import AgentFeedbackType

_FEEDBACK_COUNTS = {
    AgentFeedbackType.approved_unchanged.value: "acceptance",
    AgentFeedbackType.approved_edited.value: "edit",
    AgentFeedbackType.rejected.value: "rejection",
    AgentFeedbackType.incorrect_fact.value: "hallucination",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _pct(count: int, total: int) -> float | None:
    return round(count / total * 100, 1) if total else None


class AgentQualityService:
    """Agent quality report (sprint 3.2).

    For every agent: how humans rate its output (accept/edit/reject from
    AgentFeedback), hallucination (guard blocks + incorrect_fact feedback),
    average task time, cost/task (from LLMUsage) and human-takeover rate. The
    same feedback grouped by ``prompt_version`` lets us compare prompt
    versions and run A/B tests later.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def quality(
        self,
        *,
        company_id: uuid.UUID,
        days: int = 7,
    ) -> dict[str, Any]:
        since = _now() - timedelta(days=max(1, days))
        agents = self._agents(company_id)

        feedback_rows = self._rows(
            AgentFeedback,
            AgentFeedback.company_id == company_id,
            AgentFeedback.created_at >= since,
        )
        feedback_by_agent: dict[uuid.UUID, list[AgentFeedback]] = {}
        for fb in feedback_rows:
            if fb.agent_id is not None:
                feedback_by_agent.setdefault(fb.agent_id, []).append(fb)

        usage_rows = self._rows(
            LLMUsage,
            LLMUsage.company_id == company_id,
            LLMUsage.created_at >= since,
        )
        usage_by_agent: dict[uuid.UUID, list[LLMUsage]] = {}
        for u in usage_rows:
            if u.agent_id is not None:
                usage_by_agent.setdefault(u.agent_id, []).append(u)

        tasks = self._rows(
            Task,
            Task.company_id == company_id,
            Task.created_at >= since,
        )
        tasks_by_agent: dict[uuid.UUID, list[Task]] = {}
        for task in tasks:
            if task.agent_id is not None:
                tasks_by_agent.setdefault(task.agent_id, []).append(task)

        takeover_ids = self._takeover_conversation_ids(company_id, since)

        agent_rows: list[dict[str, Any]] = []
        for agent in agents:
            agent_rows.append(
                self._agent_metrics(
                    agent,
                    feedback_by_agent.get(agent.id, []),
                    usage_by_agent.get(agent.id, []),
                    tasks_by_agent.get(agent.id, []),
                    takeover_ids,
                )
            )

        return {
            "days": days,
            "agents": agent_rows,
            "by_prompt_version": self._by_prompt_version(
                feedback_rows, agents
            ),
        }

    # --- Per-agent --------------------------------------------------------

    def _agent_metrics(
        self,
        agent: Agent,
        feedback: list[AgentFeedback],
        usage: list[LLMUsage],
        tasks: list[Task],
        takeover_ids: set[str],
    ) -> dict[str, Any]:
        counts = self._feedback_counts(feedback)
        total_feedback = len(feedback)

        completed = [t for t in tasks if t.status.value == "completed"]
        durations = [
            (t.completed_at - t.started_at).total_seconds()
            for t in completed
            if t.completed_at is not None and t.started_at is not None
        ]

        total_cost = sum(float(u.estimated_cost_rub) for u in usage)

        return {
            "agent_id": str(agent.id),
            "name": agent.name,
            "slug": agent.slug,
            "role": agent.role,
            "tasks_total": len(tasks),
            "tasks_completed": len(completed),
            "tasks_failed": sum(1 for t in tasks if t.status.value == "failed"),
            "success_rate": _pct(len(completed), len(tasks)),
            "avg_response_seconds": round(median(durations), 2)
            if durations
            else None,
            "feedback_total": total_feedback,
            "acceptance": counts["acceptance"],
            "edit": counts["edit"],
            "rejection": counts["rejection"],
            "hallucination": counts["hallucination"],
            "acceptance_rate": _pct(counts["acceptance"], total_feedback),
            "edit_rate": _pct(counts["edit"], total_feedback),
            "rejection_rate": _pct(counts["rejection"], total_feedback),
            "hallucination_rate": _pct(counts["hallucination"], total_feedback),
            "human_takeover": self._takeover_rate(agent, tasks, takeover_ids),
            "llm_calls": len(usage),
            "total_llm_cost": round(total_cost, 2),
            "cost_per_task": round(total_cost / len(completed), 2)
            if completed
            else None,
        }

    # --- Prompt-version comparison ----------------------------------------

    def _by_prompt_version(
        self,
        feedback_rows: list[AgentFeedback],
        agents: list[Agent],
    ) -> list[dict[str, Any]]:
        by_slug = {str(a.id): a for a in agents}
        grouped: dict[tuple[str, str | None], list[AgentFeedback]] = {}
        for fb in feedback_rows:
            agent = by_slug.get(str(fb.agent_id)) if fb.agent_id else None
            key = (fb.prompt_version or "built-in", agent.slug if agent else "unknown")
            grouped.setdefault(key, []).append(fb)

        result: list[dict[str, Any]] = []
        for (version, agent_slug), rows in grouped.items():
            counts = self._feedback_counts(rows)
            total = len(rows)
            result.append(
                {
                    "agent_kind": agent_slug,
                    "prompt_version": version,
                    "feedback_total": total,
                    "acceptance": counts["acceptance"],
                    "edit": counts["edit"],
                    "rejection": counts["rejection"],
                    "hallucination": counts["hallucination"],
                    "acceptance_rate": _pct(counts["acceptance"], total),
                    "edit_rate": _pct(counts["edit"], total),
                    "rejection_rate": _pct(counts["rejection"], total),
                    "hallucination_rate": _pct(counts["hallucination"], total),
                }
            )
        result.sort(
            key=lambda r: (r["agent_kind"], r["prompt_version"] or "")
        )
        return result

    # --- Helpers ----------------------------------------------------------

    def _agents(self, company_id: uuid.UUID) -> list[Agent]:
        stmt = (
            select(Agent)
            .where(Agent.company_id == company_id)
            .order_by(Agent.created_at.asc())
        )
        return list(self.db.scalars(stmt).unique().all())

    def _rows(self, model, *conditions) -> list:
        stmt = select(model).where(*conditions)
        return list(self.db.scalars(stmt).unique().all())

    @staticmethod
    def _feedback_counts(
        feedback: list[AgentFeedback],
    ) -> dict[str, int]:
        counts = {"acceptance": 0, "edit": 0, "rejection": 0, "hallucination": 0}
        for fb in feedback:
            bucket = _FEEDBACK_COUNTS.get(fb.feedback_type.value)
            if bucket:
                counts[bucket] += 1
        return counts

    def _takeover_conversation_ids(
        self,
        company_id: uuid.UUID,
        since: datetime,
    ) -> set[str]:
        stmt = (
            select(AgentAction.target_id)
            .where(AgentAction.company_id == company_id)
            .where(AgentAction.action_type == "conversation_takeover")
            .where(AgentAction.created_at >= since)
        )
        return {str(row) for row in self.db.scalars(stmt).unique().all()}

    def _agent_conversation_ids(
        self,
        agent: Agent,
        tasks: list[Task],
    ) -> set[str]:
        """Conversations the agent worked on, linked via task input_data.

        Sprint 5.0: domain references (part_request_id / quote_id) live in the
        autoparts service, so core resolves conversations only through the
        explicit conversation_id a task always carries. Domain-side quality
        reports are computed in the autoparts service.
        """
        conv_ids: set[str] = set()
        for t in tasks:
            cid = (t.input_data or {}).get("conversation_id")
            if cid:
                conv_ids.add(str(cid))
        return conv_ids

    def _takeover_rate(
        self,
        agent: Agent,
        tasks: list[Task],
        takeover_ids: set[str],
    ) -> float | None:
        conv_ids = self._agent_conversation_ids(agent, tasks)
        if not conv_ids:
            return None
        handed = len(conv_ids & takeover_ids)
        return round(handed / len(conv_ids) * 100, 1)
