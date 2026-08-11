from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Trace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A distributed trace of one client request (sprint 3.6).

    A trace spans the whole pipeline that follows one incoming customer
    message — from the conversation span down to agent execution, LLM calls,
    supplier searches, pricing, quote and (when it happens) the order
    conversion. ``id`` is the ``trace_id`` carried by every child span.
    """

    __tablename__ = "traces"

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # root "conversation" span (started_at of the whole trace).
    root_span_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(
            "trace_spans.id", ondelete="SET NULL", use_alter=True
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Convenience metadata: what triggered the trace (e.g. "customer_message").
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="customer_message")

    spans: Mapped[list["Span"]] = relationship(
        "Span",
        back_populates="trace",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Span.started_at.asc()",
        foreign_keys="Span.trace_id",
    )
    root_span: Mapped["Span | None"] = relationship(
        "Span", foreign_keys=[root_span_id], post_update=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Trace {self.id} status={self.status} spans={len(self.spans)}>"


class Span(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One timed unit of work inside a trace.

    Types follow the pipeline: conversation, task, agent, llm, supplier,
    tool, pricing, quote, approval, action, order. A span without a parent is
    the root span of its trace (usually the conversation span).
    """

    __tablename__ = "trace_spans"

    trace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("traces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trace_spans.id", ondelete="CASCADE"), index=True, nullable=True
    )
    span_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), index=True, nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), index=True, nullable=True
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), index=True, nullable=True
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)

    trace: Mapped[Trace] = relationship(
        "Trace", back_populates="spans", foreign_keys=[trace_id]
    )
    parent: Mapped["Span | None"] = relationship(
        "Span",
        remote_side=lambda: [Span.id],
        backref="children",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Span {self.span_type} {self.name[:50]!r} status={self.status}>"


Index("ix_trace_spans_trace_parent", Span.trace_id, Span.parent_span_id)
