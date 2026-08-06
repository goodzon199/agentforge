from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class TaskMessage:
    """Unit of work submitted to the orchestrator."""

    task_id: UUID
    company_id: UUID
    objective: str
    input_data: dict[str, Any] = field(default_factory=dict)
    priority: str = "normal"
    submitted_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": str(self.task_id),
            "company_id": str(self.company_id),
            "objective": self.objective,
            "input_data": self.input_data,
            "priority": self.priority,
            "submitted_at": self.submitted_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskMessage":
        return cls(
            task_id=UUID(data["task_id"]),
            company_id=UUID(data["company_id"]),
            objective=data["objective"],
            input_data=data.get("input_data", {}),
            priority=data.get("priority", "normal"),
            submitted_at=data.get("submitted_at", ""),
        )


@dataclass
class ResultMessage:
    """Result of processing a task, produced by an agent via the orchestrator."""

    task_id: UUID
    status: str  # completed | failed
    response: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    routing_decision: dict[str, Any] = field(default_factory=dict)
    handoff_agent: str | None = None
    error: str | None = None
