from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.seeding import seed_demo

TEST_ADMIN_PASSWORD = "test-admin-pass-123"


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
    from app.core.config import settings

    settings.seed_admin_password = TEST_ADMIN_PASSWORD
    seed_demo(db, include_customer_demo=False)
    yield db
    db.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def demo_company_id(db_session):
    from app.models import Company

    return db_session.scalars(select(Company)).first().id


@pytest.fixture
def client(db_session):
    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.core.config import settings
    from app.core.redis import redis_client
    from app.main import app
    from app.models import User

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
