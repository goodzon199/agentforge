from __future__ import annotations

from app.core.seeding import seed_demo
from app.models import Agent, Company, KnowledgeEntry, PromptVersion


def test_seed_demo_creates_platform_resources(db_session):
    assert db_session.scalars(select_count(Company)).one() == 1
    assert db_session.scalars(select_count(Agent)).one() >= 2
    assert db_session.scalars(select_count(PromptVersion)).one() >= 1
    assert db_session.scalars(select_count(KnowledgeEntry)).one() >= 1


def test_seed_demo_idempotent(db_session, demo_company_id):
    from app.core.config import settings

    settings.seed_admin_password = "another-pass-456"
    result = seed_demo(db_session)
    assert result["company"] is False  # already exists, not re-created


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def select_count(model):
    from sqlalchemy import func

    return func.count(model.id)


def test_internal_health_requires_token(client):
    response = client.get("/internal/health")
    assert response.status_code == 401
