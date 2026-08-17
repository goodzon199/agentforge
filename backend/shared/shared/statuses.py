from __future__ import annotations

"""Shared status/value enums (pure Python, no SQLAlchemy).

Single source of truth for both services. ``app.models.enums`` re-exports
these so existing code keeps working unchanged.
"""

import enum


class AgentStatus(str, enum.Enum):
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
    collecting_data = "collecting_data"
    ready_for_search = "ready_for_search"
    searching = "searching"
    quoted = "quoted"
    approved = "approved"
    completed = "completed"
    cancelled = "cancelled"


class SupplierType(str, enum.Enum):
    mock = "mock"
    csv = "csv"


class SupplierSearchStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class SupplierAttemptStatus(str, enum.Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class QuoteStatus(str, enum.Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    sent = "sent"
    accepted = "accepted"
    rejected = "rejected"
    expired = "expired"
    converted_to_order = "converted_to_order"


class ApprovalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    cancelled = "cancelled"


class ApprovalRiskLevel(str, enum.Enum):
    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"


class AgentActionStatus(str, enum.Enum):
    pending = "pending"
    executed = "executed"
    failed = "failed"
    cancelled = "cancelled"


class AgentFeedbackType(str, enum.Enum):
    approved_unchanged = "approved_unchanged"
    approved_edited = "approved_edited"
    rejected = "rejected"
    incorrect_fact = "incorrect_fact"
    bad_tone = "bad_tone"
    wrong_recommendation = "wrong_recommendation"


class OrderStatus(str, enum.Enum):
    new = "new"
    confirmed = "confirmed"
    paid = "paid"
    cancelled = "cancelled"


class TrackingStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    assembling = "assembling"
    shipped = "shipped"
    arrived = "arrived"
    handed_over = "handed_over"


class ConversationMode(str, enum.Enum):
    ai_active = "ai_active"
    human_active = "human_active"
    paused = "paused"
    closed = "closed"