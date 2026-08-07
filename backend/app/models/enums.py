from __future__ import annotations

import enum


class AgentStatus(str, enum.Enum):
    """Lifecycle of a digital employee."""

    idle = "idle"
    active = "active"
    paused = "paused"
    disabled = "disabled"
    failed = "failed"


class AgentType(str, enum.Enum):
    system = "system"
    general = "general"
    specialized = "specialized"


class TaskStatus(str, enum.Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    awaiting_routing = "awaiting_routing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskPriority(str, enum.Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class LogLevel(str, enum.Enum):
    debug = "debug"
    info = "info"
    warning = "warning"
    error = "error"


class MemoryType(str, enum.Enum):
    short = "short"
    long = "long"
    knowledge = "knowledge"


class ToolStatus(str, enum.Enum):
    enabled = "enabled"
    disabled = "disabled"


class PartRequestStatus(str, enum.Enum):
    """Lifecycle of a structured request for an auto part."""

    collecting_data = "collecting_data"
    ready_for_search = "ready_for_search"
    searching = "searching"
    quoted = "quoted"
    approved = "approved"
    completed = "completed"
    cancelled = "cancelled"


class SupplierType(str, enum.Enum):
    """Adapter backend behind a supplier (mock / CSV feed)."""

    mock = "mock"
    csv = "csv"


class SupplierSearchStatus(str, enum.Enum):
    """Lifecycle of one parts-search run for a part request."""

    running = "running"
    completed = "completed"
    failed = "failed"


class SupplierAttemptStatus(str, enum.Enum):
    """Outcome of calling a single supplier adapter during a search run."""

    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class QuoteStatus(str, enum.Enum):
    """Sales funnel of a customer quote (sprint 2.5)."""

    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"
    expired = "expired"
    converted_to_order = "converted_to_order"


class ApprovalStatus(str, enum.Enum):
    """Lifecycle of an approval request raised by an agent action."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    cancelled = "cancelled"


class ApprovalRiskLevel(str, enum.Enum):
    """How much trust the platform grants an agent action.

    LOW — the agent acts alone; MEDIUM — requires company policy (approval);
    HIGH — only a human may perform it.
    """

    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"


class AgentActionStatus(str, enum.Enum):
    """Lifecycle of a recorded agent action (audit + idempotency)."""

    pending = "pending"
    executed = "executed"
    failed = "failed"
    cancelled = "cancelled"


class AgentFeedbackType(str, enum.Enum):
    """How a human corrected an agent's output (learning feedback)."""

    approved_unchanged = "approved_unchanged"
    approved_edited = "approved_edited"
    rejected = "rejected"
    incorrect_fact = "incorrect_fact"
    bad_tone = "bad_tone"
    wrong_recommendation = "wrong_recommendation"
