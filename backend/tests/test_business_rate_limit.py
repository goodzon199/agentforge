from __future__ import annotations

import uuid

from app.core.business_rate_limit import BusinessRateLimiter, category_for
from app.core.rate_limit import RateLimiter

# --- Category mapping -------------------------------------------------------


def test_category_for_mapping():
    assert category_for("GET", "/api/v1/companies") == "read"
    assert category_for("GET", "/api/v1/audit") == "read"
    assert category_for("POST", "/api/v1/companies") == "write"
    assert category_for("PATCH", "/api/v1/agents/abc") == "write"
    assert category_for("DELETE", "/api/v1/agents/abc") == "write"
    # AI markers win over method defaults.
    assert category_for("GET", "/api/v1/quotes/abc/sales-draft") == "ai"
    assert category_for("POST", "/api/v1/quotes/abc/prepare") == "ai"
    assert category_for("POST", "/api/v1/tasks/abc/replay") == "ai"
    assert category_for("POST", "/api/v1/settings/agents/abc/memory") == "ai"
    # Expensive (network-bound supplier work) markers.
    assert category_for("POST", "/api/v1/part_requests/abc/search") == "expensive"
    assert category_for("POST", "/api/v1/part_requests/abc/price") == "expensive"
    assert category_for("POST", "/api/v1/suppliers/abc/test") == "expensive"


def test_business_key_scopes_company_and_user():
    cid = uuid.uuid4()
    uid = uuid.uuid4()
    other = uuid.uuid4()
    key = BusinessRateLimiter.key("write", cid, uid)
    assert key.startswith("agentos:rate:biz:write:")
    assert str(cid) in key and str(uid) in key
    assert key != BusinessRateLimiter.key("write", cid, other)
    assert key != BusinessRateLimiter.key("read", cid, uid)


# --- End-to-end 429 via the in-memory fallback (client fixture disables Redis)


def test_write_limit_429_with_retry_after(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "business_rate_limits", {**settings.business_rate_limits, "write": {"limit": 2, "window": 60}}
    )

    def _company():
        slug = f"c-{uuid.uuid4().hex[:10]}"
        return {"name": f"Company-{slug}", "slug": slug}

    for _ in range(2):
        resp = client.post("/api/v1/companies", json=_company())
        assert resp.status_code == 201

    blocked = client.post("/api/v1/companies", json=_company())
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1


def test_read_limit_429(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "business_rate_limits", {**settings.business_rate_limits, "read": {"limit": 2, "window": 60}}
    )

    for _ in range(2):
        assert client.get("/api/v1/companies").status_code == 200
    blocked = client.get("/api/v1/companies")
    assert blocked.status_code == 429
    assert "retry-after" in blocked.headers


def test_public_login_limit_429(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(
        settings, "business_rate_limits", {**settings.business_rate_limits, "public": {"limit": 2, "window": 60}}
    )

    # The per-IP public budget is shared in the in-memory fallback across all
    # client-fixture tests (TestClient reports itself as "testclient"), so the
    # counter may already be non-zero from earlier logins. Reset it.
    from app.core.business_rate_limit import BusinessRateLimiter, get_business_rate_limiter

    get_business_rate_limiter().limiter.clear(BusinessRateLimiter.public_key("public", "testclient"))

    email = f"burst-{uuid.uuid4()}@example.com"
    for _ in range(2):
        resp = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
        assert resp.status_code == 401

    blocked = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1


# --- RateLimiter.retry_after_seconds ---------------------------------------


def test_retry_after_seconds_local(monkeypatch):
    from app.core.redis import redis_client

    monkeypatch.setattr(redis_client, "_enabled", False)
    limiter = RateLimiter()
    key = f"test:ra:{uuid.uuid4()}"

    for _ in range(3):
        assert limiter.hit(key, limit=3, window_seconds=60) is True
    assert limiter.hit(key, limit=3, window_seconds=60) is False
    retry_after = limiter.retry_after_seconds(key, 60)
    assert 1 <= retry_after <= 60
