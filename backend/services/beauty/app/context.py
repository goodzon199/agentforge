"""Beauty pack facade implementations (sprint 5.5).

Pure-SDK facades over in-memory domain state — no database. This is the
minimal amount a pack needs to give agents their ``ctx``: tools, memory,
permissions (from manifest.yaml), actions/approvals/trace/events as simple
audit logs kept in the run.
"""

from __future__ import annotations

import pathlib
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def manifest_permissions() -> set[str]:
    """Permissions the pack declares in manifest.yaml."""
    from shared.pack import load_manifest

    for candidate in (
        pathlib.Path(__file__).resolve().parents[1] / "manifest.yaml",
        pathlib.Path("/app/manifest.yaml"),
    ):
        if candidate.is_file():
            try:
                return set(load_manifest(candidate).permissions or [])
            except Exception:
                return set()
    return set()


class RunMemory:
    """In-memory memory facade (remember/recall) scoped to a run."""

    def __init__(self) -> None:
        self._items: list[str] = []

    def remember(self, content: str, kind: str = "interaction") -> None:
        self._items.append(f"[{kind}] {content}")

    def learn(self, content: str, source_task_id: Any = None) -> None:
        self._items.append(f"[learn:{source_task_id}] {content}")

    def recall(self) -> dict[str, Any]:
        return {"short": self._items, "long": []}

    def search(self, query: str) -> list[Any]:
        return []


class RunPermissions:
    """Permission gate from the manifest only (no agent record in a DB)."""

    def __init__(self) -> None:
        self._allowed = manifest_permissions()

    def require(self, *permissions: str) -> None:
        missing = [p for p in permissions if p not in self._allowed]
        if missing:
            raise PermissionError(
                f"Агенту запрещено действие: {', '.join(missing)} "
                f"(разрешены: {', '.join(sorted(self._allowed)) or 'нет'})."
            )

    def has(self, permission: str) -> bool:
        return permission in self._allowed

    def allowed(self) -> list[str]:
        return sorted(self._allowed)


class RunAudit:
    """In-memory audit log for actions/approvals/events within a run."""

    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []
        self.approvals: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def record(
        self,
        action_type: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        input_data: dict[str, Any] | None = None,
        result_data: dict[str, Any] | None = None,
        risk_level: str = "low",
        requires_approval: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "action_type": action_type,
            "target_type": target_type,
            "target_id": target_id,
            "input_data": input_data,
            "result_data": result_data,
            "risk_level": risk_level,
            "requires_approval": requires_approval,
            "idempotency_key": idempotency_key,
        }
        self.actions.append(entry)
        return entry

    def request(
        self,
        *,
        message: str,
        target_type: str | None = None,
        target_id: str | None = None,
        priority: str = "medium",
    ) -> dict[str, Any]:
        entry = {
            "action_type": "approval_request",
            "message": message,
            "target_type": target_type,
            "target_id": target_id,
            "priority": priority,
            "requires_approval": True,
        }
        self.approvals.append(entry)
        return entry

    def emit(self, message: str, *, level: str = "info", source: str | None = None) -> None:
        self.events.append({"message": message, "level": level, "source": source})


class NoopTrace:
    def span(self, span_type: str, name: str, **metadata: Any) -> Any:
        return _NoopSpan()


class _NoopSpan:
    def __enter__(self) -> _NoopSpan:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None
