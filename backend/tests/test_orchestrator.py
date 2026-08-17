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


def test_orchestrator_email_smtp_off_goes_to_dead_letter(db_session):
    """SMTP off (tests): the email task FAILS and lands in the dead-letter
    queue with a normalized kind — ready for Replay after recovery (sprint 3.5).
    """
    from app.models import DeadTask

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

    assert task.status.value == "failed"
    messages = [e.message for e in task.events]
    assert any("передал задачу агенту EmailAgent" in m for m in messages)
    dead = db_session.scalars(
        select(DeadTask).where(DeadTask.task_id == task.id)
    ).first()
    assert dead is not None
    assert dead.exception_kind == "internal_error"  # SMTP not configured
    assert dead.attempts == 1


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
    # SMTP is off in tests, so the email task fails (no statistics bump) and
    # the failure is surfaced on the task itself for retry / dead-letter.
    assert email_agent.tasks_total == 0
    assert task.status.value == "failed"
