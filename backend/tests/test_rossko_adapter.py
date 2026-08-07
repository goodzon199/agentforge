from __future__ import annotations

import asyncio
import time
from decimal import Decimal
from typing import Any

import pytest

from app.suppliers import (
    RosskoAdapter,
    SupplierAuthError,
    SupplierConnectionError,
    SupplierRateLimitError,
    SupplierResponseError,
    SupplierSearchQuery,
    SupplierTimeoutError,
    supplier_registry,
)

SOAP_WRAP = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:ns1="https://api.rossko.ru/">'
    "<SOAP-ENV:Body><ns1:GetSearchResponse><ns1:SearchResult>"
    "<ns1:success>{success}</ns1:success><ns1:text>{text}</ns1:text>"
    "<ns1:message>{message}</ns1:message>{parts}"
    "</ns1:SearchResult></ns1:GetSearchResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)


def _stock(price: str, count: str, delivery: str, stock_id: str = "HST1") -> str:
    return (
        f"<ns1:stock><ns1:id>{stock_id}</ns1:id><ns1:price>{price}</ns1:price>"
        f"<ns1:count>{count}</ns1:count><ns1:multiplicity>1</ns1:multiplicity>"
        f"<ns1:type>0</ns1:type><ns1:delivery>{delivery}</ns1:delivery>"
        f"<ns1:extra>0</ns1:extra></ns1:stock>"
    )


def _part(
    guid: str,
    brand: str,
    partnumber: str,
    name: str,
    stocks: str = "",
    crosses: str = "",
) -> str:
    return (
        f"<ns1:Part><ns1:guid>{guid}</ns1:guid><ns1:brand>{brand}</ns1:brand>"
        f"<ns1:partnumber>{partnumber}</ns1:partnumber><ns1:name>{name}</ns1:name>"
        f"<ns1:stocks>{stocks}</ns1:stocks>{crosses}</ns1:Part>"
    )


def _crosses(*parts: str) -> str:
    return "<ns1:crosses>" + "".join(parts) + "</ns1:crosses>"


def _success(*parts: str) -> str:
    return SOAP_WRAP.format(
        success="true", text="P06089", message="OK", parts="<ns1:PartsList>" + "".join(parts) + "</ns1:PartsList>"
    )


def _error(message: str) -> str:
    return SOAP_WRAP.format(success="false", text="", message=message, parts="")


def _fault(message: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
        "<SOAP-ENV:Body><SOAP-ENV:Fault>"
        "<faultcode>SOAP-ENV:Server</faultcode>"
        f"<faultstring>{message}</faultstring>"
        "</SOAP-ENV:Fault></SOAP-ENV:Body></SOAP-ENV:Envelope>"
    )


def _run(coro):
    return asyncio.run(coro)


def _settings(server, **overrides: Any) -> dict[str, Any]:
    base = {
        "base_url": f"http://127.0.0.1:{server.server_port}",
        "key1": "KEY1VALUE",
        "key2": "KEY2VALUE",
        "delivery_id": "000000002",
        "max_offers": 20,
        "max_crosses": 10,
        "min_interval": 0.01,
        "max_retries": 2,
        "backoff_base": 0.02,
        "timeout": 2.0,
    }
    base.update(overrides)
    return base


# --- Registry / setup ------------------------------------------------------


def test_registry_creates_rossko_adapter():
    adapter = supplier_registry.create(
        "rossko",
        name="Rossko",
        settings={
            "base_url": "https://api.rossko.ru",
            "key1": "k1",
            "key2": "k2",
        },
    )
    assert isinstance(adapter, RosskoAdapter)


def test_rossko_requires_keys():
    with pytest.raises(ValueError):
        RosskoAdapter(
            settings={"base_url": "https://api.rossko.ru", "key1": "k1"}
        )


# --- Search -----------------------------------------------------------------


def test_rossko_search_parses_offer_and_picks_cheapest_in_stock(fake_server):
    part = _part(
        "NSIN0000086407",
        "BREMBO",
        "P06089",
        "Тормозные колодки передние",
        stocks=_stock("2500.00", "50", "6", "HST162") + _stock("2449.85", "20", "2", "HST154"),
    )
    fake_server.behaviour = lambda path, body, headers: (200, _success(part), {})

    adapter = RosskoAdapter(name="Rossko", settings=_settings(fake_server))
    offers = _run(adapter.search(SupplierSearchQuery(article="P06089", brand="BREMBO")))

    assert len(offers) == 1
    offer = offers[0]
    assert offer.supplier_name == "Rossko"
    assert offer.brand == "BREMBO"
    assert offer.article == "P06089"
    assert offer.part_name == "Тормозные колодки передние"
    assert offer.purchase_price == Decimal("2449.85")
    assert offer.quantity == 20
    assert offer.delivery_days == 2
    assert offer.is_cross is False


def test_rossko_search_prefers_in_stock_over_cheaper(fake_server):
    part = _part(
        "NSIN0000086407",
        "BREMBO",
        "P06089",
        "Колодки",
        stocks=_stock("100.00", "0", "1", "HST1") + _stock("200.00", "5", "3", "HST2"),
    )
    fake_server.behaviour = lambda path, body, headers: (200, _success(part), {})

    adapter = RosskoAdapter(settings=_settings(fake_server))
    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))

    assert offers[0].purchase_price == Decimal("200.00")
    assert offers[0].quantity == 5
    assert offers[0].delivery_days == 3


def test_rossko_search_expands_crosses(fake_server):
    cross = _part("NSIN0000034866", "Sachs", "290 074", "Амортизатор", stocks=_stock("3297.72", "1", "0"))
    direct = _part("NSIN0000086407", "BREMBO", "P06089", "Колодки", stocks=_stock("6800.00", "4", "2"), crosses=_crosses(cross))
    fake_server.behaviour = lambda path, body, headers: (200, _success(direct), {})

    adapter = RosskoAdapter(settings=_settings(fake_server))
    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))

    assert len(offers) == 2
    by_article = {o.article: o for o in offers}
    assert by_article["P06089"].is_cross is False
    cross_offer = by_article["290 074"]
    assert cross_offer.is_cross is True
    assert cross_offer.brand == "Sachs"
    assert cross_offer.purchase_price == Decimal("3297.72")


def test_rossko_search_caps_max_offers(fake_server):
    parts = "".join(
        _part(f"G{i}", "BREMBO", f"ART{i}", f"Деталь {i}", stocks=_stock("100", "1", "1"))
        for i in range(3)
    )
    fake_server.behaviour = lambda path, body, headers: (200, _success(parts), {})
    adapter = RosskoAdapter(settings=_settings(fake_server, max_offers=2))
    offers = _run(adapter.search(SupplierSearchQuery(article="ART0")))
    assert len(offers) == 2


def test_rossko_request_body_has_keys_text_and_delivery(fake_server):
    fake_server.behaviour = lambda path, body, headers: (200, _success(), {})
    adapter = RosskoAdapter(settings=_settings(fake_server))
    _run(adapter.search(SupplierSearchQuery(article="P06089", brand="BREMBO")))

    body = fake_server.last_body
    assert "<KEY1>KEY1VALUE</KEY1>" in body
    assert "<KEY2>KEY2VALUE</KEY2>" in body
    assert "<text>BREMBO P06089</text>" in body
    assert "<delivery_id>000000002</delivery_id>" in body
    assert "soap:Envelope" in body


# --- Errors -----------------------------------------------------------------


def test_rossko_auth_error(fake_server):
    fake_server.behaviour = lambda path, body, headers: (
        500, _error("Неверные ключи доступа. Проверьте KEY1/KEY2"), {},
    )
    adapter = RosskoAdapter(name="Rossko", settings=_settings(fake_server))
    with pytest.raises(SupplierAuthError) as exc:
        _run(adapter.search(SupplierSearchQuery(article="P06089")))
    assert "ключи" in str(exc.value)
    assert adapter.requests_made == 1  # auth errors are not retried


def test_rossko_rate_limit_error(fake_server):
    fake_server.behaviour = lambda path, body, headers: (
        500, _error("Превышен лимит запросов. Попробуйте позже"), {},
    )
    adapter = RosskoAdapter(settings=_settings(fake_server))
    with pytest.raises(SupplierRateLimitError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


def test_rossko_soap_fault(fake_server):
    fake_server.behaviour = lambda path, body, headers: (500, _fault("Internal Server Error"), {})
    adapter = RosskoAdapter(settings=_settings(fake_server))
    with pytest.raises(SupplierResponseError) as exc:
        _run(adapter.search(SupplierSearchQuery(article="P06089")))
    assert "Internal Server Error" in str(exc.value)


def test_rossko_retries_500_then_succeeds(fake_server):
    calls: list[int] = []

    def behaviour(path: str, body: str, headers: dict[str, str]):
        calls.append(1)
        if len(calls) == 1:
            return 500, _error("Сервис временно недоступен"), {}
        return 200, _success(_part("G1", "BREMBO", "P06089", "Колодки", stocks=_stock("6800", "4", "2"))), {}

    fake_server.behaviour = behaviour
    adapter = RosskoAdapter(settings=_settings(fake_server, max_retries=2))
    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))

    assert len(calls) == 2
    assert len(offers) == 1
    assert adapter.requests_made == 2


def test_rossko_timeout(fake_server):
    def behaviour(path: str, body: str, headers: dict[str, str]):
        time.sleep(1.0)
        return 200, _success(), {}

    fake_server.behaviour = behaviour
    adapter = RosskoAdapter(settings=_settings(fake_server, timeout=0.15, max_retries=0))
    with pytest.raises(SupplierTimeoutError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


def test_rossko_connection_error(fake_server):
    adapter = RosskoAdapter(
        settings={
            "base_url": "http://127.0.0.1:1",
            "key1": "k1",
            "key2": "k2",
            "min_interval": 0.01,
            "max_retries": 1,
            "backoff_base": 0.02,
        }
    )
    with pytest.raises(SupplierConnectionError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


def test_rossko_rate_limit_between_requests(fake_server):
    fake_server.behaviour = lambda path, body, headers: (200, _success(), {})
    adapter = RosskoAdapter(settings=_settings(fake_server, min_interval=0.12, max_retries=0))

    start = time.monotonic()
    for _ in range(3):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))
    elapsed = time.monotonic() - start

    assert adapter.requests_made == 3
    assert elapsed >= 0.12 * 2 - 0.05


# --- Healthcheck ------------------------------------------------------------


def test_rossko_healthcheck_true_when_endpoint_reachable(fake_server):
    # A business error (bad keys) still proves the endpoint answers.
    fake_server.behaviour = lambda path, body, headers: (
        500, _error("Неверные ключи доступа"), {},
    )
    adapter = RosskoAdapter(settings=_settings(fake_server))
    assert _run(adapter.healthcheck()) is True


def test_rossko_healthcheck_false_when_unreachable(fake_server):
    fake_server.behaviour = lambda path, body, headers: (500, "", {})
    adapter = RosskoAdapter(settings=_settings(fake_server, max_retries=0))
    assert _run(adapter.healthcheck()) is False
