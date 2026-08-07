from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from tests.test_analytics import _demo_company_id, _drive_to_order


def _sales_agent(db_session):
    from app.models import Agent

    return db_session.scalars(
        select(Agent).where(Agent.slug == "sales-agent")
    ).first()


def _add_feedback(
    db_session,
    *,
    agent_id,
    feedback_type,
    company_id=None,
    prompt_version="v1",
    original="ai text",
):
    from app.models import AgentFeedback

    db_session.add(
        AgentFeedback(
            company_id=company_id or _demo_company_id(db_session),
            agent_id=agent_id,
            feedback_type=feedback_type,
            original_output=original,
            final_output="final text",
            prompt_version=prompt_version,
        )
    )


def _add_completed_task(db_session, *, agent_id, seconds_ago=5):
    from app.models import Task
    from app.models.enums import TaskPriority, TaskStatus

    now = datetime.now(timezone.utc)
    task = Task(
        company_id=_demo_company_id(db_session),
        agent_id=agent_id,
        title="task",
        objective="process_customer_message",
        status=TaskStatus.completed,
        priority=TaskPriority.normal,
        input_data={},
        started_at=now - timedelta(seconds=seconds_ago),
        completed_at=now,
    )
    db_session.add(task)
    db_session.commit()
    return task


def _add_usage(db_session, *, agent_id, task_id=None, cost="5.00"):
    from app.models import LLMUsage

    db_session.add(
        LLMUsage(
            company_id=_demo_company_id(db_session),
            agent_id=agent_id,
            task_id=task_id,
            model="gpt-4o-mini",
            prompt_tokens=1000,
            completion_tokens=100,
            total_tokens=1100,
            estimated_cost_rub=Decimal(cost),
        )
    )


def _quality(client, days=7):
    return client.get(f"/api/v1/agents/quality?days={days}").json()


def _by_slug(report, slug):
    return next(a for a in report["agents"] if a["slug"] == slug)


# --- Empty report -----------------------------------------------------------


def test_quality_empty(client, db_session):
    report = _quality(client)
    slugs = {a["slug"] for a in report["agents"]}
    assert {"intake-agent", "pricing-agent", "sales-agent", "search-agent"} <= slugs
    for a in report["agents"]:
        assert a["tasks_total"] == 0
        assert a["feedback"]["feedback_total"] == 0
        assert a["cost_per_task"] is None
    assert report["by_prompt_version"] == []


# --- Feedback rates ---------------------------------------------------------


def test_quality_feedback_rates(client, db_session):
    agent = _sales_agent(db_session)
    for _ in range(4):
        _add_feedback(db_session, agent_id=agent.id, feedback_type="approved_unchanged")
    _add_feedback(db_session, agent_id=agent.id, feedback_type="approved_edited")
    _add_feedback(db_session, agent_id=agent.id, feedback_type="rejected")
    _add_feedback(db_session, agent_id=agent.id, feedback_type="incorrect_fact")
    db_session.commit()

    report = _quality(client)
    fb = _by_slug(report, "sales-agent")["feedback"]
    assert fb["feedback_total"] == 7
    assert fb["acceptance"] == 4
    assert fb["edit"] == 1
    assert fb["rejection"] == 1
    assert fb["hallucination"] == 1
    assert fb["acceptance_rate"] == 57.1
    assert fb["edit_rate"] == 14.3
    assert fb["rejection_rate"] == 14.3
    assert fb["hallucination_rate"] == 14.3


# --- Cost + response time ---------------------------------------------------


def test_quality_cost_and_response_time(client, db_session):
    agent = _sales_agent(db_session)
    task = _add_completed_task(db_session, agent_id=agent.id, seconds_ago=10)
    _add_usage(db_session, agent_id=agent.id, task_id=task.id, cost="5.00")
    _add_usage(db_session, agent_id=agent.id, task_id=task.id, cost="5.00")
    db_session.commit()

    report = _quality(client)
    a = _by_slug(report, "sales-agent")
    assert a["tasks_completed"] == 1
    assert a["success_rate"] == 100.0
    assert a["avg_response_seconds"] == 10.0
    assert a["llm_calls"] == 2
    assert a["total_llm_cost"] == 10.0
    assert a["cost_per_task"] == 10.0


# --- Prompt version comparison ----------------------------------------------


def test_quality_by_prompt_version(client, db_session):
    agent = _sales_agent(db_session)
    for _ in range(2):
        _add_feedback(db_session, agent_id=agent.id, feedback_type="approved_unchanged", prompt_version="v1")
    _add_feedback(db_session, agent_id=agent.id, feedback_type="approved_unchanged", prompt_version="v2")
    _add_feedback(db_session, agent_id=agent.id, feedback_type="rejected", prompt_version="v2")
    db_session.commit()

    report = _quality(client)
    rows = {
        (r["agent_kind"], r["prompt_version"]): r
        for r in report["by_prompt_version"]
    }
    v1 = rows[("sales-agent", "v1")]
    v2 = rows[("sales-agent", "v2")]
    assert v1["feedback_total"] == 2
    assert v1["acceptance_rate"] == 100.0
    assert v1["rejection_rate"] == 0.0
    assert v2["feedback_total"] == 2
    assert v2["acceptance_rate"] == 50.0
    assert v2["rejection_rate"] == 50.0


# --- End-to-end: the funnel produces real quality data -----------------------


def test_quality_after_drive_to_order(client, db_session):
    _drive_to_order(client, db_session)
    report = _quality(client)

    sales = _by_slug(report, "sales-agent")
    assert sales["tasks_completed"] >= 1
    assert sales["feedback"]["feedback_total"] >= 1
    assert sales["feedback"]["acceptance"] >= 1

    intake = _by_slug(report, "intake-agent")
    assert intake["tasks_total"] >= 1

    versions = [r for r in report["by_prompt_version"] if r["agent_kind"] == "sales-agent"]
    assert versions, "ожидаем сравнение по версии промпта после реального фаннела"
    # Без LLM черновик — детерминированный шаблон (built-in), с LLM — версия v1.
    assert versions[0]["prompt_version"] in ("v1", "built-in")


# --- Cost estimation helper ---------------------------------------------------


def test_estimate_cost_rub():
    from app.core.config import settings
    from app.llm.cost import estimate_cost_rub

    settings.llm_price_rub_per_1m_input["gpt-4o-mini"] = 13.5
    settings.llm_price_rub_per_1m_output["gpt-4o-mini"] = 54.0
    cost = estimate_cost_rub("gpt-4o-mini", 100_000, 10_000)
    assert cost == Decimal("1.89")  # 1.35 + 0.54
    assert estimate_cost_rub("local-model", 100_000, 10_000) == Decimal("0")


# --- Prompts API ---------------------------------------------------------------


def test_prompts_api_list_and_create_and_activate(client, db_session):
    data = client.get("/api/v1/prompts").json()
    by_version = {p["version"]: p for p in data if p["agent_kind"] == "sales"}
    assert by_version["v1"]["is_active"] is True
    assert by_version["v2"]["is_active"] is False
    assert "SalesAgent" in by_version["v1"]["content"]

    created = client.post(
        "/api/v1/prompts",
        json={
            "agent_kind": "sales",
            "version": "v3",
            "name": "Эксперимент",
            "content": "Ты — SalesAgent, эксперимент.",
            "is_active": False,
        },
    ).json()
    assert created["version"] == "v3"

    activated = client.post(f"/api/v1/prompts/{created['id']}/activate").json()
    assert activated["is_active"] is True

    data = client.get("/api/v1/prompts").json()
    by_version = {p["version"]: p for p in data if p["agent_kind"] == "sales"}
    assert by_version["v3"]["is_active"] is True
    assert by_version["v1"]["is_active"] is False


def test_prompts_api_activate_missing_404(client, db_session):
    from uuid import uuid4

    resp = client.post(f"/api/v1/prompts/{uuid4()}/activate")
    assert resp.status_code == 404
