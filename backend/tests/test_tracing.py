from __future__ import annotations

from datetime import UTC

from sqlalchemy import select

from app.models import Span, Task, Trace


def test_customer_message_opens_trace_with_root_span(db_session, make_conversation):
    company, customer, conversation, message = make_conversation("Нужны тормозные колодки")

    trace = db_session.scalars(
        select(Trace).where(Trace.conversation_id == conversation.id)
    ).first()
    assert trace is not None
    assert trace.company_id == company.id
    assert trace.status == "running"
    assert trace.source == "customer_message"
    assert trace.root_span_id is not None

    root = db_session.get(Span, trace.root_span_id)
    assert root is not None
    assert root.span_type == "conversation"
    assert root.parent_span_id is None

    task = db_session.scalars(
        select(Task).where(Task.trace_id == trace.id)
    ).first()
    assert task is not None
    assert task.trace_id == trace.id


def test_orchestrator_records_task_agent_spans_and_finishes_trace(
    db_session, make_conversation
):
    from app.orchestrator.orchestrator import orchestrator

    company, customer, conversation, message = make_conversation("Нужны тормозные колодки")
    trace = db_session.scalars(
        select(Trace).where(Trace.conversation_id == conversation.id)
    ).first()
    task = db_session.scalars(
        select(Task).where(Task.trace_id == trace.id)
    ).first()

    orchestrator.process(db_session, task)
    db_session.refresh(trace)

    assert trace.status == "completed"
    assert trace.completed_at is not None

    spans = db_session.scalars(
        select(Span).where(Span.trace_id == trace.id)
    ).all()
    types = {s.span_type for s in spans}
    assert "task" in types
    assert "agent" in types

    task_spans = [s for s in spans if s.span_type == "task"]
    assert all(s.task_id == task.id for s in task_spans)
    assert all(s.status == "ok" for s in task_spans)
    # The task span hangs directly off the root conversation span, so the
    # whole worker chain is one tree rooted at the customer message.
    root = db_session.get(Span, trace.root_span_id)
    assert task_spans[0].parent_span_id == root.id

    # The root conversation span is closed by finish_trace.
    assert root.status == "completed"
    assert root.finished_at is not None


def test_trace_tree_endpoint(db_session, make_conversation, client):
    from app.orchestrator.orchestrator import orchestrator

    company, customer, conversation, message = make_conversation("Нужны тормозные колодки")
    trace = db_session.scalars(
        select(Trace).where(Trace.conversation_id == conversation.id)
    ).first()
    task = db_session.scalars(
        select(Task).where(Task.trace_id == trace.id)
    ).first()
    orchestrator.process(db_session, task)
    db_session.commit()

    resp = client.get("/api/v1/traces")
    assert resp.status_code == 200
    items = resp.json()
    assert any(item["id"] == str(trace.id) for item in items)
    listed = next(item for item in items if item["id"] == str(trace.id))
    assert listed["span_count"] > 0

    detail = client.get(f"/api/v1/traces/{trace.id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["trace"]["id"] == str(trace.id)
    assert payload["trace"]["status"] == "completed"
    assert payload["root"] is not None
    assert payload["root"]["span"]["span_type"] == "conversation"


def test_failed_task_marks_trace_failed(db_session, make_conversation):
    """A failed child task finishes the whole trace as failed."""
    from app.orchestrator.orchestrator import orchestrator

    company, customer, conversation, message = make_conversation("Найди тормозные колодки")
    trace = db_session.scalars(
        select(Trace).where(Trace.conversation_id == conversation.id)
    ).first()
    task = db_session.scalars(
        select(Task).where(Task.trace_id == trace.id)
    ).first()

    # The email task is guaranteed to fail (SMTP off) and is carried by the
    # same trace path as any internal task routed through the orchestrator.
    task.title = "Отправь письмо клиенту"
    task.objective = "Отправь письмо клиенту"
    db_session.flush()

    orchestrator.process(db_session, task)
    db_session.refresh(trace)

    assert trace.status == "failed"


def test_watchdog_timeout_finishes_trace_as_failed(db_session, make_conversation):
    """The task watchdog sweeps hung tasks and must also close their trace."""
    from datetime import datetime, timedelta

    from app.services.task_service import TaskService

    company, customer, conversation, message = make_conversation("Нужны тормозные колодки")
    trace = db_session.scalars(
        select(Trace).where(Trace.conversation_id == conversation.id)
    ).first()
    task = db_session.scalars(
        select(Task).where(Task.trace_id == trace.id)
    ).first()
    task.status = "running"
    task.started_at = datetime.now(UTC) - timedelta(minutes=10)
    db_session.commit()

    TaskService(db_session).mark_stale_tasks(
        max_seconds=5.0, now=datetime.now(UTC)
    )
    db_session.refresh(task)
    db_session.refresh(trace)

    assert task.status.value == "failed"
    assert "task_timeout" in task.error
    assert trace.status == "failed"
    assert trace.completed_at is not None


# --- Sprint 3.7.1: guaranteed trace completion -----------------------------


def test_span_only_trace_finalized_on_unwind(db_session):
    """A trace opened without any task must close when the block exits."""
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company
    from app.tracing.tracer import trace

    company = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    with trace(
        db_session, "api_action", "Ручное действие", company_id=company.id
    ) as sp:
        assert sp is not None
        assert sp.status == "running"

    db_session.commit()
    traces = db_session.scalars(select(Trace)).all()
    assert len(traces) == 1
    assert traces[0].status == "completed"
    assert traces[0].completed_at is not None

    root = db_session.get(Span, traces[0].root_span_id)
    assert root is not None
    assert root.status == "completed"
    assert root.finished_at is not None


def test_trace_stays_running_while_subtask_open(db_session, make_conversation):
    """Unwinding the root frame must not close a trace with open tasks."""
    from app.tracing.tracer import _finalize_on_unwind

    company, customer, conversation, message = make_conversation("Нужны тормозные колодки")
    trace = db_session.scalars(
        select(Trace).where(Trace.conversation_id == conversation.id)
    ).first()

    _finalize_on_unwind(db_session, trace.id)
    db_session.commit()
    db_session.refresh(trace)
    # The customer-message task is still pending (never processed) -> open.
    assert trace.status == "running"
    assert trace.completed_at is None


def test_reconcile_closes_orphaned_done_trace(db_session):
    """A trace whose work finished but finalization was never called closes."""
    from datetime import datetime, timedelta

    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company
    from app.models.enums import TaskPriority, TaskStatus
    from app.tracing.tracer import reconcile_stale_traces

    now = datetime.now(UTC)
    # Build a standalone trace: root span finished, task completed, but the
    # trace was never finalized (simulates a worker dying after commit).
    company = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    trace = Trace(
        company_id=company.id,
        status="running",
        started_at=now - timedelta(minutes=1),
    )
    db_session.add(trace)
    db_session.flush()
    root = Span(
        trace_id=trace.id,
        parent_span_id=None,
        span_type="conversation",
        name="r",
        status="ok",
        started_at=now - timedelta(minutes=1),
        finished_at=now,
    )
    db_session.add(root)
    db_session.flush()
    trace.root_span_id = root.id
    task = Task(
        company_id=company.id,
        agent_id=None,
        title="t",
        objective="x",
        status=TaskStatus.completed,
        priority=TaskPriority.normal,
        input_data={},
        trace_id=trace.id,
    )
    db_session.add(task)
    db_session.commit()

    assert reconcile_stale_traces(db_session, now=now) == 1
    db_session.refresh(trace)
    assert trace.status == "completed"
    assert trace.completed_at is not None


def test_reconcile_fails_abandoned_old_trace(db_session):
    """An old running trace with unfinished spans and no open tasks is failed."""
    from datetime import datetime, timedelta

    from app.tracing.tracer import reconcile_stale_traces

    now = datetime.now(UTC)
    trace = Trace(
        company_id=None,
        status="running",
        started_at=now - timedelta(hours=3),
    )
    db_session.add(trace)
    db_session.flush()
    root = Span(
        trace_id=trace.id,
        parent_span_id=None,
        span_type="conversation",
        name="r",
        status="running",
        started_at=now - timedelta(hours=3),
    )
    db_session.add(root)
    db_session.flush()
    trace.root_span_id = root.id
    db_session.commit()

    assert reconcile_stale_traces(db_session, now=now) == 1
    db_session.refresh(trace)
    assert trace.status == "failed"


def test_reconcile_keeps_trace_with_open_task(db_session, make_conversation):
    """A running trace with a non-terminal task is left alone."""
    from app.tracing.tracer import reconcile_stale_traces

    company, customer, conversation, message = make_conversation("Нужны тормозные колодки")
    trace = db_session.scalars(
        select(Trace).where(Trace.conversation_id == conversation.id)
    ).first()

    assert reconcile_stale_traces(db_session) == 0
    db_session.refresh(trace)
    assert trace.status == "running"
