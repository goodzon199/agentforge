from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, Company
from app.orchestrator.orchestrator import orchestrator
from app.services.task_service import TaskService


def test_orchestrator_processes_task(db_session):
    company = db_session.scalars(select(Company)).first()
    service = TaskService(db_session)
    task = service.create(
        company_id=company.id,
        title="Найти тормозные колодки",
        objective="Найди тормозные колодки",
    )
    db_session.commit()

    orchestrator.process(db_session, task)
    db_session.refresh(task)

    assert task.status.value == "completed"
    assert task.output_data["data"]["action"] == "search_done"
    assert task.output_data["data"]["found"] is True
    assert "TRW" in task.output_data["response"]
    messages = [e.message for e in task.events]
    assert any("передал задачу агенту SearchAgent" in m for m in messages)


def test_orchestrator_handoff_email_and_completes(db_session):
    """Email task: SystemAgent hands off to EmailAgent; SMTP is off in tests,
    so the task still completes with a clear error instead of crashing."""
    company = db_session.scalars(select(Company)).first()
    service = TaskService(db_session)
    task = service.create(
        company_id=company.id,
        title="Отправь письмо клиенту",
        objective="Отправь письмо клиенту",
    )
    db_session.commit()

    orchestrator.process(db_session, task)
    db_session.refresh(task)

    assert task.status.value == "completed"
    assert "error" in task.output_data["data"]
    messages = [e.message for e in task.events]
    assert any("передал задачу агенту EmailAgent" in m for m in messages)


def test_orchestrator_routes_to_system_without_handoff(db_session):
    company = db_session.scalars(select(Company)).first()
    service = TaskService(db_session)
    task = service.create(
        company_id=company.id,
        title="Подготовь отчёт",
        objective="Подготовь отчёт по продажам",
    )
    db_session.commit()

    orchestrator.process(db_session, task)
    db_session.refresh(task)

    assert task.status.value == "completed"
    assert task.routing_decision["needs_agent"] is None


def test_orchestrator_updates_email_agent_statistics(db_session):
    company = db_session.scalars(select(Company)).first()
    service = TaskService(db_session)
    task = service.create(
        company_id=company.id,
        title="Отправь письмо",
        objective="Отправь письмо",
    )
    db_session.commit()
    orchestrator.process(db_session, task)
    db_session.flush()

    email_agent = db_session.scalars(
        select(Agent).where(Agent.slug == "email-agent")
    ).first()
    assert email_agent.tasks_total == 1
    assert email_agent.tasks_completed == 1
    assert email_agent.avg_success_rate == 100.0
