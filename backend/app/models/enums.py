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
