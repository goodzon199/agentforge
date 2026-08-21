from __future__ import annotations

import contextvars
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Span, Task, Trace
from app.models.enums import TaskStatus

logger = logging.getLogger(__name__)

# Stack of (trace_id, span_id) frames so nested work attaches to the right
# parent span. Each worker thread / API request has its own context, so a
# sub-task (search -> pricing -> sales) inherits the same trace.
_current: contextvars.ContextVar[tuple[tuple[uuid.UUID, uuid.UUID], ...]] = (
    contextvars.ContextVar("agentos_trace_stack", default=())
)

_NON_TERMINAL = {
    TaskStatus.pending,
    TaskStatus.queued,
    TaskStatus.running,
    TaskStatus.awaiting_routing,
}

# The DB session bound to the currently executing task (set by the
# orchestrator around agent execution). Lets code without its own session
# (ToolRegistry) attach spans to the active trace.
_current_db: contextvars.ContextVar[Session | None] = contextvars.ContextVar(
    "agentos_trace_db", default=None
)


def current_db() -> Session | None:
    return _current_db.get()


def bind_db(db: Session) -> contextvars.Token:
    return _current_db.set(db)


def unbind_db(token: contextvars.Token) -> None:
    _current_db.reset(token)


def _now() -> datetime:
    return datetime.now(UTC)


def _kind(exc: BaseException) -> str:
    return type(exc).__name__


def current_trace_id() -> uuid.UUID | None:
    stack = _current.get()
    return stack[-1][0] if stack else None


def current_span_id() -> uuid.UUID | None:
    stack = _current.get()
    return stack[-1][1] if stack else None


# --- Trace lifecycle -------------------------------------------------------


def begin_trace(
    db: Session,
    *,
    company_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None = None,
    source: str = "customer_message",
    name: str = "Обработка сообщения",
) -> Trace:
    """Create a new trace with its root "conversation" span."""
    trace = Trace(
        company_id=company_id,
        conversation_id=conversation_id,
        status="running",
        started_at=_now(),
        source=source,
    )
    db.add(trace)
    db.flush()
    root = Span(
        trace_id=trace.id,
        parent_span_id=None,
        span_type="conversation",
        name=name,
        status="running",
        started_at=_now(),
        meta={"source": source},
    )
    db.add(root)
    db.flush()
    trace.root_span_id = root.id
    db.flush()
    # Make the root span the active parent for subsequent spans created in the
    # same context (the API request that opened the trace).
    _current.set((*_current.get(), (trace.id, root.id)))
    return trace


def finish_trace(db: Session, trace_id: uuid.UUID, *, status: str = "completed") -> None:
    """Mark a trace (and its root span) completed."""
    trace = db.get(Trace, trace_id)
    if trace is None:
        return
    trace.status = status
    trace.completed_at = _now()
    if trace.root_span_id is not None:
        root = db.get(Span, trace.root_span_id)
        if root is not None and root.finished_at is None:
            root.status = status
            root.finished_at = _now()
            root.duration_ms = _duration_ms(root.started_at, root.finished_at)
    db.flush()


def maybe_finish_trace(db: Session, trace_id: uuid.UUID | None) -> None:
    """Finish the trace once every task of it reached a terminal state."""
    if trace_id is None:
        return
    open_tasks = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.trace_id == trace_id, Task.status.in_(_NON_TERMINAL))
    )
    if open_tasks:
        return
    failed = db.scalar(
        select(func.count())
        .select_from(Task)
        .where(Task.trace_id == trace_id, Task.status == TaskStatus.failed)
    )
    status = "failed" if failed else "completed"
    finish_trace(db, trace_id, status=status)


def _finalize_on_unwind(db: Session, trace_id: uuid.UUID) -> None:
    """Trigger trace finalization when all of its span frames unwound.

    Called from the ``trace`` contextmanager after the outermost frame is
    popped. Two shapes are recognised as "fully unwound":

      * the context stack for this trace is empty (worker thread), or
      * only the dangling root frame remains — the marker ``begin_trace``
        left on the API request's stack that nothing ever pops.

    ``maybe_finish_trace`` closes the trace (and its root span) once every
    task reached a terminal state; if more work is still queued the trace
    legitimately stays ``running``. This is the guarantee that a trace can
    never stay ``running`` after its work finished, even when no task ever
    referenced it (span-only traces).
    """
    trace = db.get(Trace, trace_id)
    if trace is None or trace.status != "running":
        return
    frames = [f for f in _current.get() if f[0] == trace_id]
    if len(frames) > 1:
        return  # deeper frames for this trace are still active
    if len(frames) == 1 and frames[0][1] != trace.root_span_id:
        return  # the remaining frame is not this trace's root marker
    maybe_finish_trace(db, trace_id)


def reconcile_stale_traces(
    db: Session,
    *,
    max_age_seconds: float = 600.0,
    now: datetime | None = None,
) -> int:
    """Watchdog: no trace may stay ``running`` forever.

    Closes traces whose every task reached a terminal state even when
    ``maybe_finish_trace`` was never called for them (span-only traces,
    a worker that died between the last task and the finalization call).
    Traces still running after ``max_age_seconds`` with no open tasks are
    closed too (marked failed when spans are left unfinished). Returns how
    many traces were closed.
    """
    now = now or _now()
    age_limit = now - timedelta(seconds=max_age_seconds)
    running = list(
        db.scalars(select(Trace).where(Trace.status == "running")).unique().all()
    )
    closed = 0
    for trace in running:
        open_tasks = db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.trace_id == trace.id, Task.status.in_(_NON_TERMINAL))
        )
        if open_tasks:
            continue
        unfinished = db.scalar(
            select(func.count())
            .select_from(Span)
            .where(Span.trace_id == trace.id, Span.finished_at.is_(None))
        )
        if unfinished and trace.started_at >= age_limit:
            continue  # young trace with active spans — give it more time
        failed = db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.trace_id == trace.id, Task.status == TaskStatus.failed)
        )
        status = "failed" if (failed or unfinished) else "completed"
        finish_trace(db, trace.id, status=status)
        closed += 1
    if closed:
        db.commit()
    return closed


def resolve_trace_for_conversation(
    db: Session,
    conversation_id: uuid.UUID | None,
    *,
    company_id: uuid.UUID | None = None,
    source: str = "api_action",
) -> uuid.UUID | None:
    """Return the latest trace of a conversation (creating one if missing).

    Used by API-triggered actions (order conversion, approval) that run outside
    a worker trace context but must still join the conversation's trace.
    """
    active = current_trace_id()
    if active is not None:
        return active
    if conversation_id is not None:
        trace = db.scalar(
            select(Trace)
            .where(Trace.conversation_id == conversation_id)
            .order_by(Trace.created_at.desc())
            .limit(1)
        )
        if trace is not None:
            return trace.id
    if company_id is None:
        return None
    return begin_trace(
        db, company_id=company_id, conversation_id=conversation_id, source=source
    ).id


def _duration_ms(started_at: datetime, finished_at: datetime) -> int:
    # SQLite returns naive datetimes even for timezone=True columns; normalise
    # both sides so timedelta arithmetic never mixes naive and aware values.
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=UTC)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=UTC)
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


# --- Span recording --------------------------------------------------------


def _span_row(
    *,
    trace_id: uuid.UUID,
    parent_span_id: uuid.UUID | None,
    span_type: str,
    name: str,
    task_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    supplier_id: uuid.UUID | None,
    order_id: uuid.UUID | None,
    status: str,
    started_at: datetime,
    finished_at: datetime | None,
    metadata: dict[str, Any] | None,
    error_kind: str | None,
) -> Span:
    return Span(
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        span_type=span_type,
        name=name,
        task_id=task_id,
        agent_id=agent_id,
        supplier_id=supplier_id,
        order_id=order_id,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=(
            _duration_ms(started_at, finished_at) if finished_at is not None else None
        ),
        meta=metadata or {},
        error_kind=error_kind,
    )


@contextmanager
def trace(
    db: Session,
    span_type: str,
    name: str,
    *,
    company_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    trace_id: uuid.UUID | None = None,
    parent_span_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[Span]:
    """Record a span and make it the parent for nested spans.

    When no trace is active and none is passed, a new trace is started so
    spans are never lost (idempotent: root span type is "conversation").
    """
    tid = trace_id or current_trace_id()
    if tid is None:
        begin_trace(
            db,
            company_id=company_id,
            conversation_id=conversation_id,
            source=metadata.get("source", "auto") if metadata else "auto",
            name=name,
        )
        tid = current_trace_id()
        if tid is None:
            yield None  # type: ignore[misc]  # pragma: no cover
            return

    parent = parent_span_id if parent_span_id is not None else current_span_id()
    sp = _span_row(
        trace_id=tid,
        parent_span_id=parent,
        span_type=span_type,
        name=name,
        task_id=task_id,
        agent_id=agent_id,
        supplier_id=supplier_id,
        order_id=order_id,
        status="running",
        started_at=_now(),
        finished_at=None,
        metadata=metadata,
        error_kind=None,
    )
    db.add(sp)
    db.flush()
    token = _current.set((*_current.get(), (tid, sp.id)))
    try:
        yield sp
    except Exception as exc:
        sp.status = "failed"
        sp.error_kind = _kind(exc)
        raise
    else:
        sp.status = "ok"
    finally:
        sp.finished_at = _now()
        sp.duration_ms = _duration_ms(sp.started_at, sp.finished_at)
        _current.reset(token)
        try:
            db.flush()
        except Exception:  # pragma: no cover - tracing must not break the flow
            logger.exception("Не удалось сохранить спан %s", span_type)
        # Guarantee: once the last frame of this trace unwound, close the
        # trace so it can never stay "running" after its work finished.
        try:
            _finalize_on_unwind(db, tid)
            db.flush()
        except Exception:  # pragma: no cover
            logger.exception("Не удалось финализировать трассировку %s", tid)


def record_span(
    db: Session,
    span_type: str,
    name: str,
    *,
    trace_id: uuid.UUID | None = None,
    parent_span_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    duration_ms: int = 0,
    status: str = "ok",
    error_kind: str | None = None,
    metadata: dict[str, Any] | None = None,
    started_at: datetime | None = None,
) -> Span | None:
    """Record a finished span (no nesting), e.g. per-supplier attempts."""
    tid = trace_id or current_trace_id()
    if tid is None:
        return None
    parent = parent_span_id if parent_span_id is not None else current_span_id()
    start = started_at or _now()
    finished = start + timedelta(milliseconds=max(0, duration_ms))
    sp = _span_row(
        trace_id=tid,
        parent_span_id=parent,
        span_type=span_type,
        name=name,
        task_id=task_id,
        agent_id=agent_id,
        supplier_id=supplier_id,
        order_id=order_id,
        status=status,
        started_at=start,
        finished_at=finished,
        metadata=metadata,
        error_kind=error_kind,
    )
    db.add(sp)
    db.flush()
    return sp


class SpanRecorder:
    """Buffered span writer for code paths without a session (LLM proxy).

    The orchestrator flushes recorded spans together with LLMUsage rows, so
    tracing stays consistent with the existing idempotent usage flush.
    """

    def __init__(self) -> None:
        self._spans: list[dict[str, Any]] = []

    def record(
        self,
        span_type: str,
        name: str,
        *,
        status: str,
        duration_ms: int,
        trace_id: uuid.UUID | None = None,
        parent_span_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
        error_kind: str | None = None,
    ) -> None:
        self._spans.append(
            {
                "span_type": span_type,
                "name": name,
                "status": status,
                "duration_ms": duration_ms,
                "trace_id": trace_id,
                "parent_span_id": parent_span_id,
                "metadata": metadata or {},
                "error_kind": error_kind,
            }
        )

    def clear(self) -> None:
        self._spans = []

    def flush(self, db: Session, *, task_id: uuid.UUID | None = None) -> int:
        """Persist buffered spans. Returns how many rows were written."""
        if not self._spans:
            return 0
        written = 0
        for s in self._spans:
            tid = s["trace_id"] or current_trace_id()
            if tid is None:
                continue
            parent = s["parent_span_id"] if s["parent_span_id"] is not None else current_span_id()
            start = _now()
            finished = start + timedelta(milliseconds=max(0, s["duration_ms"]))
            db.add(
                _span_row(
                    trace_id=tid,
                    parent_span_id=parent,
                    span_type=s["span_type"],
                    name=s["name"],
                    task_id=task_id,
                    agent_id=None,
                    supplier_id=None,
                    order_id=None,
                    status=s["status"],
                    started_at=start,
                    finished_at=finished,
                    metadata=s["metadata"],
                    error_kind=s["error_kind"],
                )
            )
            written += 1
        self.clear()
        return written
