from __future__ import annotations

from app.models import AgentAction, Task, TaskEvent
from app.models.enums import AgentActionStatus, ApprovalRiskLevel
from app.services.usage_service import UsageService


def _company_id(db_session):
    from app.models import Company

    return db_session.query(Company).first().id


def _agent_id(db_session):
    from app.models import Agent

    return db_session.query(Agent).first().id


def test_usage_empty_summary(db_session, demo_company_id):
    summary = UsageService(db_session).summary(30, scope=demo_company_id)
    assert summary["days"] == 30
    assert summary["totals"]["workflow_runs"] == 0
    assert summary["totals"]["agent_executions"] == 0
    assert summary["by_pack"] == []
    assert summary["by_workflow"] == []


def test_usage_counts_workflow_runs_and_attribution(db_session, demo_company_id):
    task = Task(
        company_id=demo_company_id,
        title="t",
        objective="o",
        status="completed",
    )
    db_session.add(task)
    db_session.flush()
    db_session.add(
        TaskEvent(
            task_id=task.id,
            source="workflow_runtime",
            message="workflow booking_pipeline стартует",
            meta={"workflow": "booking_pipeline", "pack": "beauty"},
        )
    )
    db_session.commit()

    summary = UsageService(db_session).summary(30, scope=demo_company_id)
    assert summary["totals"]["workflow_runs"] == 1
    assert summary["totals"]["tasks_total"] >= 1
    assert any(b["pack"] == "beauty" and b["workflow_runs"] == 1 for b in summary["by_pack"])
    assert any(b["workflow"] == "booking_pipeline" for b in summary["by_workflow"])


def test_usage_counts_agent_executions_and_tool_calls(db_session, demo_company_id):
    agent_id = _agent_id(db_session)
    task = Task(company_id=demo_company_id, title="t", objective="o", status="completed")
    db_session.add(task)
    db_session.flush()
    db_session.add(
        AgentAction(
            company_id=demo_company_id,
            agent_id=agent_id,
            task_id=task.id,
            action_type="calendar_book",
            status=AgentActionStatus.executed,
            requires_approval=False,
            risk_level=ApprovalRiskLevel.low,
        )
    )
    db_session.add(
        AgentAction(
            company_id=demo_company_id,
            agent_id=agent_id,
            task_id=task.id,
            action_type="workflow_human",
            status=AgentActionStatus.pending,
            requires_approval=True,
            risk_level=ApprovalRiskLevel.medium,
        )
    )
    db_session.commit()

    summary = UsageService(db_session).summary(30, scope=demo_company_id)
    assert summary["totals"]["agent_executions"] >= 2
    assert summary["totals"]["tool_calls"] >= 1  # calendar_book counted
    assert summary["totals"]["approvals_pending"] >= 1
    assert any(b["agent_id"] == str(agent_id) for b in summary["by_agent"])


def test_usage_tenant_scope_filters_other_company(db_session, demo_company_id):
    from app.models import Company

    other = Company(
        name="Other", slug="other-usage", description="", is_active=True, agent_quota=3
    )
    db_session.add(other)
    db_session.flush()
    db_session.add(Task(company_id=other.id, title="t", objective="o", status="pending"))
    db_session.commit()

    scoped = UsageService(db_session).summary(30, scope=demo_company_id)
    unscoped = UsageService(db_session).summary(30, scope=None)
    assert scoped["totals"]["tasks_total"] < unscoped["totals"]["tasks_total"]
