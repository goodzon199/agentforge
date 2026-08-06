from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.suppliers import (
    CsvSupplierAdapter,
    MockSupplierAdapter,
    SupplierSearchQuery,
    normalize_article,
    supplier_registry,
)


def _run(coro):
    return asyncio.run(coro)


def test_normalize_article_uppercases_and_keeps_alnum_only():
    assert normalize_article("BREMBO P06089") == "BREMBOP06089"
    assert normalize_article("p060-89") == "P06089"
    assert normalize_article("  gdb 2119  ") == "GDB2119"
    assert normalize_article("") == ""


def test_mock_adapter_returns_stable_catalog():
    adapter = MockSupplierAdapter(name="АвтоТорг")
    offers = _run(adapter.search(SupplierSearchQuery(part_name="колодки")))

    assert len(offers) == 2
    by_article = {o.article: o for o in offers}
    assert by_article["P06089"].brand == "BREMBO"
    assert by_article["P06089"].purchase_price == Decimal("6800.00")
    assert by_article["GDB2119"].brand == "TRW"
    assert by_article["GDB2119"].purchase_price == Decimal("6100.00")
    assert all(o.supplier_name == "АвтоТорг" for o in offers)


def test_mock_adapter_filters_by_article():
    adapter = MockSupplierAdapter(name="АвтоТорг")
    offers = _run(adapter.search(SupplierSearchQuery(article="GDB2119")))
    assert len(offers) == 1
    assert offers[0].article == "GDB2119"


def test_mock_adapter_healthcheck():
    adapter = MockSupplierAdapter(name="АвтоТорг")
    assert _run(adapter.healthcheck()) is True


def test_csv_adapter_reads_and_filters_feed(tmp_path):
    feed = tmp_path / "feed.csv"
    feed.write_text(
        "brand;article;name;price;quantity;delivery_days\n"
        "BREMBO;P06089;Тормозные колодки;6800,00;4;2\n"
        "TRW;GDB2119;Тормозные колодки;6100.00;3;1\n",
        encoding="utf-8",
    )
    adapter = CsvSupplierAdapter(
        name="CSV-поставщик",
        settings={
            "file_path": str(feed),
            "delimiter": ";",
            "encoding": "utf-8",
        },
    )
    offers = _run(adapter.search(SupplierSearchQuery(article="P06089")))
    assert len(offers) == 1
    assert offers[0].brand == "BREMBO"
    assert offers[0].purchase_price == Decimal("6800.00")
    assert offers[0].quantity == 4
    assert offers[0].delivery_days == 2


def test_csv_adapter_missing_file_raises():
    adapter = CsvSupplierAdapter(settings={"file_path": "/nonexistent/feed.csv"})
    with pytest.raises(FileNotFoundError):
        _run(adapter.search(SupplierSearchQuery(article="P06089")))


def test_registry_creates_adapters_by_type():
    assert isinstance(
        supplier_registry.create("mock", name="A"), MockSupplierAdapter
    )
    assert isinstance(
        supplier_registry.create("csv", name="B"), CsvSupplierAdapter
    )


def test_registry_unknown_type_raises():
    with pytest.raises(ValueError):
        supplier_registry.create("does-not-exist")
