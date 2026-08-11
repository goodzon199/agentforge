from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class SpanRead(ORMModel):
    id: uuid.UUID
    trace_id: uuid.UUID
    parent_span_id: uuid.UUID | None
    span_type: str
    name: str
    agent_id: uuid.UUID | None
    task_id: uuid.UUID | None
    supplier_id: uuid.UUID | None
    order_id: uuid.UUID | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    meta: dict[str, Any]
    error_kind: str | None


class TraceRead(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    root_span_id: uuid.UUID | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    source: str
    created_at: datetime
    span_count: int = 0


class TraceSummary(ORMModel):
    id: uuid.UUID
    company_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    source: str
    created_at: datetime
    span_count: int = 0
    error_kinds: list[str] = []


class TraceDetail(TraceRead):
    spans: list[SpanRead] = []


class SpanNode(BaseModel):
    """A span plus its children, for tree rendering on the frontend."""

    span: SpanRead
    children: list["SpanNode"] = []


class TraceTree(BaseModel):
    trace: TraceSummary
    root: SpanNode | None = None


SpanNode.model_rebuild()
