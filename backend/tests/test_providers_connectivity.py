from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from app.models import Company
from app.services.supplier_service import SupplierService
from app.suppliers import (
    ArmtekAdapter,
    AvtokontinentAdapter,
    AvtorustAdapter,
    HttpSupplierAdapter,
    NormalizedSupplierOffer,
    ShatemAdapter,
    SupplierAdapter,
    SupplierSearchQuery,
    supplier_registry,
)
from app.suppliers.base import ExternalOrderResult, SupplierOrderData
from app.suppliers.errors import SupplierQueryNotSupported


def _run(coro):
    return asyncio.run(coro)


def _company_id(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG

    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id


def _settings(server, **overrides: Any) -> dict[str, Any]:
    base = {
        "base_url": f"http://127.0.0.1:{server.server_port}",
        "search_path": "/search",
        "auth": {"mode": "api_key", "key_header": "X-Api-Key", "value": "secret"},
        "offers_key": "data.offers",
        "min_interval": 0.01,
        "max_retries": 0,
        "backoff_base": 0.02,
        "timeout": 2.0,
    }
    base.update(overrides)
    return base


# --- KPI: a new provider connects via the existing SupplierAdapter ----------


class _BrandNewProviderAdapter(SupplierAdapter):
    """A provider added AFTER the platform shipped — nothing in the core
    knows it exists. It implements only the existing contract."""

    type = "kpi_brand_new"

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        return [
            NormalizedSupplierOffer(
                supplier_name=self.name,
                brand="NOVO",
                article="X-1",
                part_name="Колодки",
                purchase_price=Decimal("1500.00"),
                quantity=1,
                delivery_days=1,
            )
        ]

    async def order(self, *, data: SupplierOrderData) -> ExternalOrderResult:
        return ExternalOrderResult(external_order_id="NOVO-42", status="accepted")

    async def order_status(self, external_order_id: str) -> str:
        return "arrived"


@pytest.fixture
def _brand_new_provider():
    supplier_registry.register(_BrandNewProviderAdapter)
    yield
    supplier_registry._adapters.pop(_BrandNewProviderAdapter.type, None)


def test_kpi_new_provider_connects_without_core_changes(db_session, _brand_new_provider):
    """Sprint 4.7 KPI: adding a supplier = a registered SupplierAdapter + a
    Supplier row with that adapter_type. No service/API/model changes needed."""
    service = SupplierService(db_session)
    supplier = service.create(
        company_id=_company_id(db_session),
        name="Бренд-нью поставщик",
        adapter_type=_BrandNewProviderAdapter.type,
    )
    db_session.add(supplier)
    db_session.commit()

    adapter = service.adapter_for(supplier)
    offers = _run(adapter.search(SupplierSearchQuery(article="X-1")))
    assert len(offers) == 1
    assert offers[0].article == "X-1"
    result = _run(
        adapter.order(
            data=SupplierOrderData(order_number="ORD-9", items=[{"article": "X-1"}])
        )
    )
    assert result.external_order_id == "NOVO-42"
    assert _run(adapter.order_status("NOVO-42")) == "arrived"


def test_kpi_provider_registered_through_registry_only(db_session, _brand_new_provider):
    """The existing adapter_type validation accepts the new provider."""
    from app.services.supplier_service import SupplierService

    supplier = SupplierService(db_session).create(
        company_id=_company_id(db_session),
        name="Новый",
        adapter_type=_BrandNewProviderAdapter.type,
    )
    assert supplier.adapter_type == _BrandNewProviderAdapter.type
    assert _BrandNewProviderAdapter.type in supplier_registry.types()


# --- Presets are thin subclasses of HttpSupplierAdapter ----------------------


def test_real_provider_presets_registered():
    types = supplier_registry.types()
    for name in ("armtek", "shatem", "avtorust", "avtokontinent"):
        assert name in types


def test_real_provider_presets_are_http_adapter_subclasses():
    for cls in (ArmtekAdapter, ShatemAdapter, AvtorustAdapter, AvtokontinentAdapter):
        adapter = cls(name=cls.type)
        assert isinstance(adapter, HttpSupplierAdapter)
        assert adapter.type == cls.type
        assert adapter.base_url


def test_registry_creates_real_provider_instances():
    assert isinstance(
        supplier_registry.create("armtek", name="A"), ArmtekAdapter
    )
    assert isinstance(
        supplier_registry.create("shatem", name="B"), ShatemAdapter
    )
    assert isinstance(
        supplier_registry.create("avtorust", name="C"), AvtorustAdapter
    )
    assert isinstance(
        supplier_registry.create("avtokontinent", name="D"), AvtokontinentAdapter
    )


def test_unverified_providers_marked_experimental():
    """Sprint 4.7 presets have no confirmed live API — never production-ready.

    The platform must expose this on SupplierRead so operators are not misled.
    """
    for adapter_type in ("armtek", "shatem", "avtorust", "avtokontinent"):
        assert supplier_registry.is_experimental(adapter_type) is True, adapter_type
    # Established, live-tested adapters are production-ready by default.
    assert supplier_registry.is_experimental("mock") is False
    assert supplier_registry.is_experimental("rossko") is False


# --- Config-driven order placement / tracking --------------------------------


def test_http_adapter_order_places_and_returns_external_id(fake_server):
    fake_server.behaviour = (
        lambda path, body, headers: (200, {"data": {"orderId": "EXT-77"}}, {})
    )
    adapter = HttpSupplierAdapter(
        name="HTTP",
        settings=_settings(
            fake_server,
            order={
                "path": "/orders",
                "method": "POST",
                "external_order_id": "data.orderId",
                "status": "data.status",
            },
        ),
    )
    result = _run(
        adapter.order(
            data=SupplierOrderData(order_number="ORD-1", items=[{"article": "P1"}])
        )
    )
    assert result.external_order_id == "EXT-77"
    assert result.status == "accepted"
    assert fake_server.last_method == "POST"
    body = json.loads(fake_server.last_body)
    assert body["order_number"] == "ORD-1"


def test_http_adapter_order_with_body_template(fake_server):
    fake_server.behaviour = (
        lambda path, body, headers: (200, {"data": {"id": "42", "status": "new"}}, {})
    )
    adapter = HttpSupplierAdapter(
        name="HTTP",
        settings=_settings(
            fake_server,
            order={
                "path": "/orders",
                "body": {"number": "{order_number}", "positions": "{items}"},
                "external_order_id": "data.id",
                "status": "data.status",
                "status_mapping": {"new": "accepted"},
            },
        ),
    )
    result = _run(
        adapter.order(
            data=SupplierOrderData(
                order_number="ORD-2",
                items=[{"article": "P1", "brand": "B", "quantity": 2}],
            )
        )
    )
    assert result.external_order_id == "42"
    assert result.status == "accepted"
    body = json.loads(fake_server.last_body)
    assert body["number"] == "ORD-2"
    assert body["positions"][0]["article"] == "P1"


def test_http_adapter_order_without_config_raises_query_not_supported(fake_server):
    adapter = HttpSupplierAdapter(name="HTTP", settings=_settings(fake_server))
    with pytest.raises(SupplierQueryNotSupported):
        _run(
            adapter.order(
                data=SupplierOrderData(
                    order_number="ORD-3", items=[{"article": "P1"}]
                )
            )
        )


def test_http_adapter_order_status_polls_and_maps(fake_server):
    fake_server.behaviour = (
        lambda path, body, headers: (200, {"data": {"status": "shipped"}}, {})
    )
    adapter = HttpSupplierAdapter(
        name="HTTP",
        settings=_settings(
            fake_server,
            status={
                "path": "/orders/{external_order_id}",
                "status": "data.status",
            },
        ),
    )
    status = _run(adapter.order_status("EXT-77"))
    assert status == "shipped"
    assert fake_server.last_path == "/orders/EXT-77"


def test_http_adapter_order_status_maps_provider_vocabulary(fake_server):
    fake_server.behaviour = (
        lambda path, body, headers: (200, {"data": {"status": "transferring"}}, {})
    )
    adapter = HttpSupplierAdapter(
        name="HTTP",
        settings=_settings(
            fake_server,
            status={
                "path": "/orders/{external_order_id}",
                "status": "data.status",
                "status_mapping": {"transferring": "shipped"},
            },
        ),
    )
    assert _run(adapter.order_status("E1")) == "shipped"


def test_http_adapter_order_status_unknown_status_defaults(fake_server):
    fake_server.behaviour = (
        lambda path, body, headers: (200, {"data": {"status": "???"}}, {})
    )
    adapter = HttpSupplierAdapter(
        name="HTTP",
        settings=_settings(
            fake_server,
            status={"path": "/o/{external_order_id}", "status": "data.status"},
        ),
    )
    assert _run(adapter.order_status("E1")) == "unknown"


def test_http_adapter_order_status_without_config_raises(fake_server):
    adapter = HttpSupplierAdapter(name="HTTP", settings=_settings(fake_server))
    with pytest.raises(SupplierQueryNotSupported):
        _run(adapter.order_status("E1"))


# --- SupplierService.adapter_for builds presets from a Supplier row ----------


def test_adapter_for_builds_preset_from_supplier_row(db_session):
    service = SupplierService(db_session)
    supplier = service.create(
        company_id=_company_id(db_session),
        name="Армтек",
        adapter_type="armtek",
    )
    adapter = service.adapter_for(supplier)
    assert isinstance(adapter, ArmtekAdapter)
    assert adapter.base_url == "https://api.armtek.ru"
