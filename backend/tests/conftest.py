from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.seeding import seed_demo

Behaviour = Callable[[str], tuple[int, Any, dict[str, str]]]

TEST_ADMIN_PASSWORD = "test-admin-pass-123"


class _FakeServerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._serve()

    def do_POST(self) -> None:
        self._serve()

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        self.server.last_method = self.command  # type: ignore[attr-defined]
        self.server.last_path = self.path  # type: ignore[attr-defined]
        self.server.last_headers = dict(self.headers)  # type: ignore[attr-defined]
        self.server.last_body = self.rfile.read(length).decode("utf-8", "replace")  # type: ignore[attr-defined]
        status, payload, headers = self.server.behaviour(  # type: ignore[attr-defined]
            self.path, self.server.last_body, dict(self.headers)
        )
        if isinstance(payload, str):
            body = payload.encode("utf-8")
            ctype = headers.pop("Content-Type", "text/xml; charset=utf-8")
        else:
            body = json.dumps(payload).encode("utf-8")
            ctype = "application/json"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


@pytest.fixture
def fake_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeServerHandler)
    server.behaviour: Behaviour = lambda path, body, headers: (200, {}, {})  # type: ignore[attr-defined]
    server.last_method = ""  # type: ignore[attr-defined]
    server.last_path = ""  # type: ignore[attr-defined]
    server.last_headers: dict[str, str] = {}  # type: ignore[attr-defined]
    server.last_body = ""  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _reset_trace_context():
    """Isolate the tracing context between tests.

    ``begin_trace`` pushes its root frame onto the thread-local contextvar
    and nothing pops it (the frame is normally discarded with the FastAPI
    request context). In synchronous tests that frame leaks into the next
    test and would make ``trace()`` attach to a stale trace instead of
    opening a new one.
    """
    from app.tracing import tracer

    tracer._current.set(())
    yield
    tracer._current.set(())


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
    # The bootstrap admin is only created when an explicit password is set
    # (no hardcoded demo credentials anymore). Give the test DB a strong one.
    from app.core.config import settings

    settings.seed_admin_password = TEST_ADMIN_PASSWORD
    # Customer-facing demo data (reliability telemetry, garage customer with
    # orders) is skipped so tests do not depend on demo customers/orders in
    # global queries (e.g. select(PartRequest).first()).
    seed_demo(db, include_customer_demo=False)
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
