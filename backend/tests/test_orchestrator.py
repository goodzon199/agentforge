from __future__ import annotations

from sqlalchemy import select

from app.models import Company
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
    assert task.routing_decision["needs_agent"] == "SearchAgent"
    assert task.output_data["response"] == "Для выполнения этой задачи нужен SearchAgent."
    assert len(task.events) >= 2


def test_orchestrator_updates_agent_statistics(db_session):
    from sqlalchemy import select

    from app.models import Agent

    company = db_session.scalars(select(Agent)).first().company
    service = TaskService(db_session)
    task = service.create(
        company_id=company.id,
        title="Отправь письмо",
        objective="Отправь письмо",
    )
    db_session.commit()
    orchestrator.process(db_session, task)
    db_session.flush()

    agent = db_session.scalars(select(Agent)).first()
    assert agent.tasks_total == 1
    assert agent.tasks_completed == 1
    assert agent.avg_success_rate == 100.0
