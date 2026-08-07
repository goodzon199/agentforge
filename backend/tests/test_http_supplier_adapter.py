from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any

import pytest

from app.suppliers import (
    HttpSupplierAdapter,
    SupplierAuthError,
    SupplierConnectionError,
    SupplierParseError,
    SupplierRateLimitError,
    SupplierResponseError,
    SupplierSearchQuery,
    SupplierTimeoutError,
    supplier_registry,
)


def _run(coro):
    return asyncio.run(coro)


def _settings(server, **overrides: Any) -> dict[str, Any]:
    base = {
        "base_url": f"http://127.0.0.1:{server.server_port}",
        "search_path": "/search",
        "auth": {"mode": "api_key", "key_header": "X-Api-Key", "value": "secret"},
        "offers_key": "data.offers",
        "crosses_key": "data.crosses",
        "min_interval": 0.01,
        "max_retries": 2,
        "backoff_base": 0.02,
        "timeout": 2.0,
    }
    base.update(overrides)
    return base


def _offer(article: str = "P06089", **overrides: Any) -> dict[str, Any]:
    row = {
        "article": article,
        "brand": "BREMBO",
        "name": "Тормозные колодки",
        "price": "6800.00",
        "quantity": 4,
        "delivery_days": 2,
    }
    row.update(overrides)
    return row


# --- Registry / setup ------------------------------------------------------


def test_registry_creates_http_adapter():
    adapter = supplier_registry.create(
        "http", name="Rossko", settings={"base_url": "https://api.rossko.ru"}
    )
    assert isinstance(adapter, HttpSupplierAdapter)


def test_http_adapter_requires_base_url():
    with pytest.raises(ValueError):
        HttpSupplierAdapter(settings={"auth": {"mode": "api_key"}})


# --- Search: happy path ----------------------------------------------------


def test_search_normalizes_offers(fake_server):
    def behaviour(path: str, body: str, headers: dict[str, str]):
        calls.append(path)
        return 200, {"data": {"offers": [_offer()]}}, {}

    calls: list[str] = []
    fake_server.behaviour = behaviour
    adapter = HttpSupplierAdapter(name="Rossko", settings=_settings(fake_server))

    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))

    assert len(offers) == 1
    offer = offers[0]
    assert offer.supplier_name == "Rossko"
    assert offer.article == "P06089"
    assert offer.brand == "BREMBO"
    assert offer.purchase_price == Decimal("6800.00")
    assert offer.quantity == 4
    assert offer.delivery_days == 2
    assert offer.is_cross is False
    assert "/search" in calls[0]
    assert "P06089" in calls[0]


# --- Auth ------------------------------------------------------------------


def test_search_sends_api_key_header(fake_server):
    fake_server.behaviour = lambda path, body, headers: (200, {"data": {"offers": [_offer()]}}, {})
    adapter = HttpSupplierAdapter(settings=_settings(fake_server))
    _run(adapter.search(SupplierSearchQuery(article="P06089")))
    assert fake_server.last_headers.get("X-Api-Key") == "secret"


def test_search_sends_bearer_token(fake_server):
    fake_server.behaviour = lambda path, body, headers: (200, {"data": {"offers": [_offer()]}}, {})
    settings = _settings(
        fake_server, auth={"mode": "bearer", "token": "tok123"}
    )
    adapter = HttpSupplierAdapter(settings=settings)
    _run(adapter.search(SupplierSearchQuery(article="P06089")))
    assert fake_server.last_headers.get("Authorization") == "Bearer tok123"


def test_search_auth_error_401(fake_server):
    fake_server.behaviour = lambda path, body, headers: (401, {"error": "unauthorized"}, {})
    adapter = HttpSupplierAdapter(settings=_settings(fake_server, max_retries=1))
    with pytest.raises(SupplierAuthError) as exc:
        _run(adapter.search(SupplierSearchQuery(article="P06089")))
    assert "401" in str(exc.value)


# --- Crosses ---------------------------------------------------------------


def test_search_expands_crosses_as_is_cross(fake_server):
    payload = {
        "data": {
            "offers": [_offer()],
            "crosses": [_offer("GDB2119", brand="TRW", price="6100.00", quantity=3, delivery_days=1)],
        }
    }
    fake_server.behaviour = lambda path, body, headers: (200, payload, {})
    adapter = HttpSupplierAdapter(settings=_settings(fake_server))

    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))

    assert len(offers) == 2
    direct = next(o for o in offers if o.article == "P06089")
    cross = next(o for o in offers if o.article == "GDB2119")
    assert direct.is_cross is False
    assert cross.is_cross is True
    assert cross.brand == "TRW"
    assert cross.purchase_price == Decimal("6100.00")
    assert cross.quantity == 3
    assert cross.delivery_days == 1


def test_search_without_crosses_key_ignores_analogs(fake_server):
    payload = {"data": {"offers": [_offer()], "crosses": [_offer("GDB2119")]}}
    fake_server.behaviour = lambda path, body, headers: (200, payload, {})
    adapter = HttpSupplierAdapter(
        settings=_settings(fake_server, crosses_key=None)
    )
    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))
    assert len(offers) == 1


# --- Errors ----------------------------------------------------------------


def test_search_parse_error_on_bad_structure(fake_server):
    fake_server.behaviour = lambda path, body, headers: (200, {"data": {"offers": {"not": "a list"}}}, {})
    adapter = HttpSupplierAdapter(settings=_settings(fake_server))
    with pytest.raises(SupplierParseError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


def test_search_raises_parse_error_when_offer_missing_article(fake_server):
    fake_server.behaviour = lambda path, body, headers: (200, {"data": {"offers": [{"brand": "BREMBO"}]}}, {})
    adapter = HttpSupplierAdapter(settings=_settings(fake_server))
    with pytest.raises(SupplierParseError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


def test_search_response_error_after_retries(fake_server):
    calls: list[int] = []
    fake_server.behaviour = (
        lambda path, body, headers: (calls.append(503) or (503, {"error": "busy"}, {}))
    )
    adapter = HttpSupplierAdapter(settings=_settings(fake_server, max_retries=2))
    with pytest.raises(SupplierResponseError) as exc:
        _run(adapter.search(SupplierSearchQuery(article="P06089")))
    assert calls.count(503) == 3  # initial + 2 retries
    assert "503" in str(exc.value)


def test_search_connection_error(fake_server):
    adapter = HttpSupplierAdapter(
        settings={
            "base_url": "http://127.0.0.1:1",  # nothing listens on port 1
            "min_interval": 0.01,
            "max_retries": 1,
            "backoff_base": 0.02,
        }
    )
    with pytest.raises(SupplierConnectionError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


# --- Retry -----------------------------------------------------------------


def test_search_retries_500_then_succeeds(fake_server):
    calls: list[int] = []

    def behaviour(path: str, body: str, headers: dict[str, str]):
        calls.append(1)
        if len(calls) == 1:
            return 500, {"error": "boom"}, {}
        return 200, {"data": {"offers": [_offer()]}}, {}

    fake_server.behaviour = behaviour
    adapter = HttpSupplierAdapter(settings=_settings(fake_server, max_retries=2))

    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))

    assert len(calls) == 2
    assert len(offers) == 1
    assert adapter.requests_made == 2


def test_search_429_honors_retry_after_then_succeeds(fake_server):
    calls: list[int] = []

    def behaviour(path: str, body: str, headers: dict[str, str]):
        calls.append(1)
        if len(calls) == 1:
            return 429, {"error": "slow down"}, {"Retry-After": "0"}
        return 200, {"data": {"offers": [_offer()]}}, {}

    fake_server.behaviour = behaviour
    adapter = HttpSupplierAdapter(settings=_settings(fake_server, max_retries=2))

    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))

    assert len(offers) == 1
    assert len(calls) == 2


def test_search_429_exhausts_retries_raises_rate_limit(fake_server):
    fake_server.behaviour = (
        lambda path, body, headers: (429, {"error": "slow down"}, {"Retry-After": "0"})
    )
    adapter = HttpSupplierAdapter(settings=_settings(fake_server, max_retries=1))
    with pytest.raises(SupplierRateLimitError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


# --- Timeout ---------------------------------------------------------------


def test_search_timeout(fake_server):
    def behaviour(path: str, body: str, headers: dict[str, str]):
        time.sleep(1.0)
        return 200, {"data": {"offers": [_offer()]}}, {}

    fake_server.behaviour = behaviour
    adapter = HttpSupplierAdapter(settings=_settings(fake_server, timeout=0.15, max_retries=0))
    with pytest.raises(SupplierTimeoutError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


# --- Rate limiting ---------------------------------------------------------


def test_rate_limit_min_interval_between_requests(fake_server):
    fake_server.behaviour = lambda path, body, headers: (200, {"data": {"offers": [_offer()]}}, {})
    adapter = HttpSupplierAdapter(
        settings=_settings(fake_server, min_interval=0.12, max_retries=0)
    )

    start = time.monotonic()
    for _ in range(3):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))
    elapsed = time.monotonic() - start

    assert adapter.requests_made == 3
    assert elapsed >= 0.12 * 2 - 0.05  # two gaps between three requests


# --- Healthcheck -----------------------------------------------------------


def test_healthcheck_true_on_2xx(fake_server):
    fake_server.behaviour = lambda path, body, headers: (200, {"status": "ok"}, {})
    adapter = HttpSupplierAdapter(settings=_settings(fake_server))
    assert _run(adapter.healthcheck()) is True


def test_healthcheck_false_on_error(fake_server):
    fake_server.behaviour = lambda path, body, headers: (503, {"error": "down"}, {})
    adapter = HttpSupplierAdapter(settings=_settings(fake_server))
    assert _run(adapter.healthcheck()) is False
