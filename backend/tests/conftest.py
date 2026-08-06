from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.seeding import seed_demo


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(
        bind=engine, autocommit=False, autoflush=False, expire_on_commit=False
    )
    Base.metadata.create_all(engine)
    db = TestingSession()
    seed_demo(db)
    yield db
    db.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def demo_company_id(db_session):
    from app.models import Company

    return db_session.scalars(select(Company)).first().id


@pytest.fixture
def make_conversation(db_session):
    """Create a demo company, a customer and a conversation with one customer message."""

    def _make(content: str, customer_name: str = "Иван Петров"):
        from app.core.seeding import DEMO_COMPANY_SLUG
        from app.models import Company
        from app.services.conversation_service import ConversationService

        company = db_session.scalars(
            select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
        ).first()
        cs = ConversationService(db_session)
        customer = cs.create_customer(company_id=company.id, name=customer_name)
        db_session.add(customer)
        db_session.flush()
        conversation = cs.create_conversation(
            company_id=company.id, customer_id=customer.id, channel="web"
        )
        db_session.add(conversation)
        db_session.flush()
        message, _ = cs.add_message(conversation, content=content, sender_type="customer")
        db_session.commit()
        return company, customer, conversation, message

    return _make


@pytest.fixture
def client(db_session):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.core.config import settings
    from app.core.redis import redis_client
    from app.main import app
    from app.models import User

    # Tests run synchronously: force the in-process path even if a real
    # Redis is reachable on localhost (e.g. the docker compose stack is up).
    saved_enabled = redis_client._enabled
    redis_client._enabled = False

    admin = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()

    def override_get_db():
        yield db_session

    def override_get_current_user():
        return admin

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
    redis_client._enabled = saved_enabled
