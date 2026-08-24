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


def test_login_throttle_keys_are_redis_namespaced(monkeypatch):
    from app.core.rate_limit import LoginThrottle

    assert LoginThrottle._ip_key("1.2.3.4") == "agentos:auth:ip:1.2.3.4"
    assert LoginThrottle._fail_key("Admin@AgentOS.local") == "agentos:auth:user:admin@agentos.local"
    assert LoginThrottle._lock_key("Admin@AgentOS.local") == "agentos:auth:lock:admin@agentos.local"


def test_login_throttle_locks_after_failures(db_session):
    import uuid

    from app.core.config import settings
    from app.core.rate_limit import LoginThrottle

    throttle = LoginThrottle()
    email = f"user-{uuid.uuid4().hex[:8]}@agentos.local"
    assert throttle.is_locked(email) is False
    for _ in range(settings.login_failures_before_lock):
        throttle.record_failure(email)
    assert throttle.is_locked(email) is True
    throttle.record_success(email)
    assert throttle.is_locked(email) is False
    throttle.limiter.clear(throttle._fail_key(email))
    throttle.clear_state_for_test()


def test_login_throttle_ip_budget(db_session):
    import uuid

    from app.core.config import settings
    from app.core.rate_limit import LoginThrottle, RateLimiter
    from app.core.redis import RedisClient

    # Hermetic: pin the limiter to its in-memory store. With a reachable
    # Redis each hit() pays a ping, and on a slow host the 25-call loop can
    # outlive the rate window, resetting the counter mid-test.
    throttle = LoginThrottle(
        limiter=RateLimiter(RedisClient(settings.redis_url, enabled=False))
    )
    ip = f"198.51.{uuid.uuid4().hex[:8]}"  # unique per run (Redis keys persist between runs)
    allowed = sum(throttle.request_allowed(ip) for _ in range(settings.login_rate_per_minute + 5))
    assert allowed == settings.login_rate_per_minute
    assert throttle.request_allowed(ip) is False
    throttle.limiter.clear(throttle._ip_key(ip))
    throttle.clear_state_for_test()


def test_pilot_aggregates_pack_metrics(db_session, monkeypatch):
    """Core rolls up /internal/metrics from active packs into /analytics/pilot."""
    import uuid

    from app.models import Pack
    from app.services.analytics_service import AnalyticsService

    monkeypatch.setattr(
        "shared.internal.internal_get",
        lambda *args, **kwargs: {
            "namespace": "autoparts",
            "metrics": {
                "suppliers": {"attempts_total": 100, "success_rate": 97.4},
                "orders": 5,
                "revenue": 250000.0,
                "quotes_sent": 12,
                "part_requests_total": 30,
            },
        },
    )
    db_session.add(
        Pack(
            id=uuid.uuid4(),
            name="autoparts",
            version="1.0.0",
            display_name="AutoParts",
            base_url="http://autoparts:8012",
            is_active=True,
        )
    )
    db_session.commit()

    data = AnalyticsService(db_session).pilot(company_id=uuid.uuid4(), days=7)
    assert data["packs"][0]["status"] == "ok"
    assert data["packs"][0]["namespace"] == "autoparts"
    assert data["orders_total"] == 5
    assert data["quotes_sent"] == 12
    assert data["part_requests_total"] == 30
    assert data["revenue"] == "250000.00"
    assert data["suppliers"]["attempts_total"] == 100
    assert data["suppliers"]["failure_rate"] == 2.6


def test_pilot_reports_unavailable_pack(db_session):
    """A registered but unreachable pack is reported as unavailable, not null."""
    import uuid

    from app.models import Pack
    from app.services.analytics_service import AnalyticsService

    db_session.add(
        Pack(
            id=uuid.uuid4(),
            name="deadpack",
            version="1.0.0",
            display_name="Dead Pack",
            base_url="http://127.0.0.1:1",  # nothing listens here
            is_active=True,
        )
    )
    db_session.commit()

    data = AnalyticsService(db_session).pilot(company_id=uuid.uuid4(), days=7)
    assert data["packs"][0]["status"] == "unavailable"
    assert data["packs"][0]["namespace"] == "deadpack"
    assert data["orders_total"] == 0
    assert data["revenue"] == "0.00"
    assert data["suppliers"]["attempts_total"] == 0
