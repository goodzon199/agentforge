from __future__ import annotations

import pytest
from sqlalchemy import create_engine
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
def client(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()
