from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select


def _demo_company_id(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company

    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id


def _make_conversation(client, db_session) -> str:
    customer = client.post(
        "/api/v1/customers",
        json={"company_id": str(_demo_company_id(db_session)), "name": "Иван"},
    ).json()["id"]
    return client.post(
        "/api/v1/conversations",
        json={"company_id": str(_demo_company_id(db_session)), "customer_id": customer},
    ).json()["id"]


def _drive_to_order(client, db_session) -> tuple[str, str, str]:
    """Run the whole funnel: dialog -> VIN -> search -> pricing -> quote ->
    send -> approve -> accept -> order. Returns (conversation_id, quote_id, order_id)."""
    conversation_id = _make_conversation(client, db_session)
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны передние колодки на BMW X5 2019"},
    )
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Вот VIN WBAKS410900H12345"},
    )
    part_request = client.get(
        f"/api/v1/part_requests?conversation_id={conversation_id}"
    ).json()[0]
    quote_id = client.get(f"/api/v1/part_requests/{part_request['id']}/quote").json()["quote_id"]

    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    send = client.post(
        f"/api/v1/quotes/{quote_id}/send", json={"message": draft["ai_draft"]}
    ).json()
    client.post(f"/api/v1/approvals/{send['approval_id']}/approve")

    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Да, беру TRW, заказ подтверждаю"},
    )
    converted = client.post(f"/api/v1/quotes/{quote_id}/convert").json()
    return conversation_id, quote_id, converted["order_id"]


# --- Analytics endpoint -----------------------------------------------------


def test_pilot_empty(client, db_session):
    data = client.get("/api/v1/analytics/pilot?days=7").json()
    assert data["requests_total"] == 0
    assert data["conversations_total"] == 0
    assert data["ai_handled"] == 0
    assert data["handed_to_manager"] == 0
    assert data["takeover_rate"] == 0.0
    assert data["orders_total"] == 0
    assert data["revenue"] == "0.00"
    assert data["gross_profit"] == "0.00"
    assert data["avg_response_seconds"] is None
    assert [p["objective"] for p in data["pipeline"]] == [
        "process_customer_message",
        "search_parts",
        "pricing_parts",
        "sales_draft",
    ]


def test_pilot_counts_money_and_response_time(client, db_session):
    _drive_to_order(client, db_session)
    data = client.get("/api/v1/analytics/pilot?days=7").json()

    assert data["requests_total"] == 3  # 3 customer messages
    assert data["conversations_total"] == 1
    assert data["ai_handled"] == 1  # the AI replied in that conversation
    assert data["quotes_sent"] == 1
    assert data["quotes_accepted"] == 1
    assert data["orders_total"] == 1
    assert data["revenue"] == "7930.00"
    # margin 30% on both priced offers in the order snapshot:
    #   TRW 6100 -> total 7930, profit 7930*30/130 = 1830
    #   BREMBO 6800 -> total 8840, profit 8840*30/130 = 2040
    assert data["gross_profit"] == "3870.00"
    assert data["avg_response_seconds"] is not None

    by_objective = {p["objective"]: p for p in data["pipeline"]}
    assert by_objective["search_parts"]["count"] == 1
    assert by_objective["search_parts"]["on_sla_pct"] == 100.0
    assert by_objective["pricing_parts"]["count"] == 1
    assert by_objective["sales_draft"]["count"] == 1

    assert data["suppliers"]["attempts_total"] == 1  # один активный демо-поставщик
    assert data["suppliers"]["failure_rate"] == 0.0
    assert data["suppliers"]["avg_latency_ms"] is not None

    assert data["llm"]["available"] is False
    assert data["llm"]["failure_rate"] == 0.0
    assert data["task_timeouts"] == 0


def test_pilot_takeover_metrics(client, db_session):
    conversation_id = _make_conversation(client, db_session)
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"sender_type": "customer", "content": "Нужны колодки на BMW X5"},
    )
    client.post(f"/api/v1/conversations/{conversation_id}/takeover")

    data = client.get("/api/v1/analytics/pilot?days=7").json()
    assert data["conversations_total"] == 1
    assert data["handed_to_manager"] == 1
    assert data["takeover_rate"] == 100.0


# --- Watchdog ---------------------------------------------------------------


def _stale_task(db_session, objective="process_customer_message", minutes_ago=10):
    from app.models import Task
    from app.models.enums import TaskPriority, TaskStatus

    task = Task(
        company_id=_demo_company_id(db_session),
        title="stale",
        objective=objective,
        status=TaskStatus.running,
        priority=TaskPriority.normal,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_mark_stale_tasks_watchdog(client, db_session):
    from app.services.task_service import TaskService

    stale = _stale_task(db_session)
    failed = TaskService(db_session).mark_stale_tasks(max_seconds=60)
    assert failed == 1
    db_session.refresh(stale)
    assert stale.status.value == "failed"
    assert "task_timeout" in stale.error

    data = client.get("/api/v1/analytics/pilot?days=7").json()
    assert data["task_timeouts"] == 1


def test_mark_stale_tasks_is_idempotent_across_sweepers(client, db_session):
    """Several workers may sweep the same tick; the task must get exactly one
    task_timeout event (guard against duplicate watchdog events)."""
    from sqlalchemy import func, select

    from app.models import TaskEvent
    from app.services.task_service import TaskService

    stale = _stale_task(db_session)
    svc = TaskService(db_session)
    first = svc.mark_stale_tasks(max_seconds=60)
    second = svc.mark_stale_tasks(max_seconds=60)
    third = svc.mark_stale_tasks(max_seconds=60)
    assert first == 1
    assert second == 0
    assert third == 0

    events = db_session.scalars(
        select(TaskEvent).where(TaskEvent.task_id == stale.id)
    ).all()
    timeouts = [e for e in events if e.message.startswith("task_timeout")]
    assert len(timeouts) == 1


def test_mark_stale_search_runs(client, db_session):
    import uuid as uuid_mod

    from app.models import PartRequest, SupplierSearchRun
    from app.models.enums import PartRequestStatus, SupplierSearchStatus
    from app.services.parts_search_service import PartsSearchService

    company_id = _demo_company_id(db_session)
    customer = client.post(
        "/api/v1/customers",
        json={"company_id": str(company_id), "name": "Иван"},
    ).json()["id"]
    conversation = client.post(
        "/api/v1/conversations",
        json={"company_id": str(company_id), "customer_id": customer},
    ).json()["id"]
    pr = PartRequest(
        company_id=company_id,
        conversation_id=uuid_mod.UUID(conversation),
        customer_id=uuid_mod.UUID(customer),
        part_name="колодки",
        status=PartRequestStatus.searching,
        structured_data={},
    )
    db_session.add(pr)
    db_session.flush()
    run = SupplierSearchRun(
        part_request_id=pr.id,
        status=SupplierSearchStatus.running,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        structured_data={},
    )
    db_session.add(run)
    db_session.commit()

    failed = PartsSearchService(db_session).mark_stale_runs(max_seconds=60)
    assert failed == 1
    db_session.refresh(run)
    assert run.status.value == "failed"
    assert "supplier_failed" in run.error
    db_session.refresh(pr)
    assert pr.status == PartRequestStatus.ready_for_search
