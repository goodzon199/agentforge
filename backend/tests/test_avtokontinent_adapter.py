from __future__ import annotations

import asyncio
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from app.suppliers import (
    AvtokontinentAdapter,
    SupplierAuthError,
    SupplierOrderData,
    SupplierQueryNotSupported,
    SupplierResponseError,
    SupplierSearchQuery,
)


def _run(coro):
    return asyncio.run(coro)


def _settings(server, **overrides):
    base = {
        "base_url": f"http://127.0.0.1:{server.server_port}",
        "auth": {"mode": "basic", "username": "user", "password": "pass"},
        "min_interval": 0.01,
        "max_retries": 0,
        "timeout": 2.0,
        "max_cards": 10,
    }
    base.update(overrides)
    return base


def _part_response():
    return [
        {
            "part_id": 13151369,
            "part_code": "ph5883",
            "brand_name": "Fram",
            "part_descr": "Фильтр масляный",
        }
    ]


def _price_response():
    return [
        {
            "part_id": 13151369,
            "part_code": "ph5883",
            "part_name": "Фильтр масляный",
            "brand_name": "Fram",
            "warehouse_id": 1,
            "warehouse_name": "Москва",
            "price": 340,
            "currency_id": 1,
            "currency_name": "RUB",
            "quantity": "12",
            "dt_delivery": "2099-01-01 10:00:00",
        },
        {
            "part_id": 13151369,
            "part_code": "ph5883X",
            "part_name": "Фильтр масляный (аналог)",
            "brand_name": "Fram",
            "warehouse_id": 2,
            "warehouse_name": "СПб",
            "price": 360,
            "quantity": "5",
            "dt_delivery": "2099-01-02 10:00:00",
        },
    ]


def _route(behaviour):
    def handler(path, body, headers):
        method = path.split("/v1/", 1)[-1].split(".json", 1)[0]
        return behaviour(method, parse_qs(urlparse(path).query), headers)

    return handler


# --- Search ----------------------------------------------------------------


def test_search_two_step_part_then_price(fake_server):
    routes = {
        "search/part": (200, _part_response(), {}),
        "search/price": (200, _price_response(), {}),
    }
    fake_server.behaviour = _route(
        lambda method, qs, headers: routes.get(method, (404, {}, {}))
    )
    adapter = AvtokontinentAdapter(settings=_settings(fake_server))
    offers = _run(adapter.search(SupplierSearchQuery(article="ph5883")))

    assert len(offers) == 2
    direct = offers[0]
    assert direct.brand == "Fram"
    assert direct.article == "ph5883"
    assert direct.part_name == "Фильтр масляный"
    assert direct.purchase_price == Decimal("340")
    assert direct.quantity == 12
    assert direct.is_cross is False
    assert offers[1].is_cross is True
    assert offers[1].article == "ph5883X"


def test_search_requires_article(fake_server):
    adapter = AvtokontinentAdapter(settings=_settings(fake_server))
    with pytest.raises(SupplierQueryNotSupported):
        _run(adapter.search(SupplierSearchQuery(part_name="масло")))


# --- Order / status ---------------------------------------------------------


def test_order_fills_basket_and_returns_newest_order_id(fake_server):
    calls: list[tuple[str, dict]] = []

    def behaviour(method, qs, headers):
        calls.append((method, {k: v[0] for k, v in qs.items()}))
        if method == "search/part":
            return 200, _part_response(), {}
        if method == "search/price":
            return 200, _price_response(), {}
        if method == "basket/add":
            return 200, {"status": "ok", "basket_id": 10}, {}
        if method == "basket/order":
            return 200, {"status": "ok"}, {}
        if method == "order/get":
            return (
                200,
                [
                    {"order_id": 77, "state": 1, "part_code": "ph5883"},
                    {"order_id": 78, "state": 1, "part_code": "ph5883"},
                ],
                {},
            )
        return 404, {}, {}

    fake_server.behaviour = _route(behaviour)
    adapter = AvtokontinentAdapter(settings=_settings(fake_server))
    result = _run(
        adapter.order(
            data=SupplierOrderData(
                order_number="ORD-1",
                items=[{"article": "ph5883", "quantity": 2}],
            )
        )
    )
    assert result.external_order_id == "78"
    assert result.status == "accepted"

    by_name = dict(calls)
    assert by_name["basket/add"]["part_id"] == "13151369"
    assert by_name["basket/add"]["warehouse_id"] == "1"
    assert by_name["basket/add"]["quantity"] == "2"
    assert by_name["basket/order"]["delivery_mode_id"] == "1"


def test_order_raises_when_basket_rejects(fake_server):
    def behaviour(method, qs, headers):
        if method == "search/part":
            return 200, _part_response(), {}
        if method == "search/price":
            return 200, _price_response(), {}
        if method == "basket/add":
            return 200, {"status": "error"}, {}
        return 404, {}, {}

    fake_server.behaviour = _route(behaviour)
    adapter = AvtokontinentAdapter(settings=_settings(fake_server))
    with pytest.raises(SupplierResponseError):
        _run(
            adapter.order(
                data=SupplierOrderData(
                    order_number="ORD-1", items=[{"article": "ph5883"}]
                )
            )
        )


@pytest.mark.parametrize(
    "state,expected",
    [
        (1, "accepted"),
        (4, "assembling"),
        (5, "shipped"),
        (8, "arrived"),
        (12, "arrived"),
        (14, "delivered"),
    ],
)
def test_order_status_maps_state(fake_server, state, expected):
    def behaviour(method, qs, headers):
        if method == "order/get":
            return 200, [{"order_id": 5, "state": state}], {}
        return 404, {}, {}

    fake_server.behaviour = _route(behaviour)
    adapter = AvtokontinentAdapter(settings=_settings(fake_server))
    assert _run(adapter.order_status("5")) == expected


def test_order_status_refusal_maps_unknown(fake_server):
    def behaviour(method, qs, headers):
        if method == "order/get":
            return 200, [{"order_id": 5, "state": 7}], {}
        return 404, {}, {}

    fake_server.behaviour = _route(behaviour)
    adapter = AvtokontinentAdapter(settings=_settings(fake_server))
    assert _run(adapter.order_status("5")) == "unknown"


def test_order_status_unknown_order(fake_server):
    fake_server.behaviour = _route(
        lambda method, qs, headers: (200, [{"order_id": 9, "state": 4}], {})
    )
    adapter = AvtokontinentAdapter(settings=_settings(fake_server))
    assert _run(adapter.order_status("999")) == "unknown"


# --- Auth errors ------------------------------------------------------------


def test_error_code_1_is_auth_error(fake_server):
    fake_server.behaviour = _route(
        lambda method, qs, headers: (
            200,
            {"error_code": 1, "error_message": "Ошибка авторизации"},
            {},
        )
    )
    adapter = AvtokontinentAdapter(settings=_settings(fake_server))
    with pytest.raises(SupplierAuthError):
        _run(adapter.search(SupplierSearchQuery(article="ph5883")))
