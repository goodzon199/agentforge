from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Company, SupplierOffer
from app.services.parts_search_service import PartsSearchService
from app.services.pricing_service import PricingService
from app.suppliers.base import NormalizedSupplierOffer, SupplierAdapter, SupplierSearchQuery
from app.suppliers.registry import supplier_registry


@pytest.fixture(autouse=True)
def _custom_adapters():
    classes = (_NoPriceAdapter, _EmptyAdapter)
    for cls in classes:
        supplier_registry.register(cls)
    yield
    for cls in classes:
        supplier_registry._adapters.pop(cls.type, None)


def _company_id(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG

    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id


def _make_part_request(db_session, *, article="", quantity=1):
    from app.models.enums import PartRequestStatus as PRS
    from app.services.conversation_service import ConversationService
    from app.services.part_request_service import PartRequestService

    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=_company_id(db_session), name="Иван Петров")
    db_session.add(customer)
    db_session.flush()
    conversation = cs.create_conversation(
        company_id=_company_id(db_session), customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    pr = PartRequestService(db_session).create(
        company_id=_company_id(db_session),
        conversation_id=conversation.id,
        customer_id=customer.id,
        source_message_id=None,
        part_name="Тормозные колодки",
        article=article,
        quantity=quantity,
        status=PRS.ready_for_search,
    )
    db_session.add(pr)
    db_session.commit()
    return pr


def _seeded_supplier(db_session):
    from app.core.seeding import DEMO_SUPPLIERS
    from app.models import Supplier

    return db_session.scalars(
        select(Supplier).where(Supplier.slug == DEMO_SUPPLIERS[0]["slug"])
    ).first()


def _add_supplier(db_session, *, name, adapter_type):
    from app.models import Supplier

    supplier = Supplier(
        company_id=_company_id(db_session),
        name=name,
        slug=f"{name}-{uuid.uuid4().hex[:6]}".lower(),
        adapter_type=adapter_type,
        is_active=True,
        settings={},
    )
    db_session.add(supplier)
    db_session.commit()
    return supplier


def _search(db_session, part_request):
    result = PartsSearchService(db_session).search(part_request, triggered_by="user")
    db_session.commit()
    return result


class _NoPriceAdapter(SupplierAdapter):
    type = "no_price"

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        return [
            NormalizedSupplierOffer(
                supplier_name=self.name, brand="B", article="X1",
                purchase_price=None, quantity=1, delivery_days=3,
            )
        ]


class _EmptyAdapter(SupplierAdapter):
    type = "empty_pricing"

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        return []


# --- Calculations -----------------------------------------------------------

def test_price_applies_margin(db_session):
    assert PricingService(db_session).price(Decimal("6100.00"), Decimal("30")) == Decimal("7930.00")
    assert PricingService(db_session).price(Decimal("6800.00"), Decimal("30")) == Decimal("8840.00")


def test_price_rounds_half_up(db_session):
    assert PricingService(db_session).price(Decimal("99.99"), Decimal("10")) == Decimal("109.99")
    assert PricingService(db_session).price(Decimal("100.05"), Decimal("10")) == Decimal("110.06")


# --- Process ----------------------------------------------------------------

def test_process_stamps_offers_and_summary(db_session):
    pr = _make_part_request(db_session)
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id, triggered_by="agent")

    assert summary["status"] == "priced"
    assert summary["offers_priced"] == 2
    assert summary["best_article"] == "GDB2119"
    assert summary["best_unit_price"] == "7930.00"
    assert summary["best_total_price"] == "7930.00"
    assert summary["margin_percent"] == 30.0

    offers = PartsSearchService(db_session).list_offers(pr.id)
    by_article = {o.article: o for o in offers}
    assert by_article["GDB2119"].customer_price == Decimal("7930.00")
    assert by_article["P06089"].customer_price == Decimal("8840.00")
    assert by_article["GDB2119"].total_price == Decimal("7930.00")
    assert by_article["GDB2119"].margin_percent == Decimal("30.00")

    db_session.refresh(pr)
    assert pr.structured_data["pricing"]["status"] == "priced"


def test_process_uses_company_margin_override(db_session):
    company = db_session.scalars(select(Company)).first()
    company.settings = {"pricing": {"margin_percent": 10}}
    db_session.commit()

    pr = _make_part_request(db_session)
    _search(db_session, pr)
    summary = PricingService(db_session).process(pr.id)

    assert summary["margin_percent"] == 10.0
    assert summary["best_unit_price"] == "6710.00"  # 6100 * 1.1
    offers = PartsSearchService(db_session).list_offers(pr.id)
    by_article = {o.article: o for o in offers}
    assert by_article["P06089"].customer_price == Decimal("7480.00")


def test_process_totals_account_for_quantity(db_session):
    pr = _make_part_request(db_session, quantity=2)
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id)
    assert summary["quantity"] == 2
    assert summary["best_unit_price"] == "7930.00"
    assert summary["best_total_price"] == "15860.00"  # 7930 * 2


def test_process_without_offers_returns_no_offers(db_session):
    _seeded_supplier(db_session).is_active = False
    db_session.commit()
    _add_supplier(db_session, name="Пусто", adapter_type="empty_pricing")
    pr = _make_part_request(db_session)
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id)
    assert summary["status"] == "no_offers"
    assert summary["offers_priced"] == 0
    assert summary["best_offer_id"] is None


def test_process_skips_offers_without_purchase_price(db_session):
    _seeded_supplier(db_session).is_active = False
    db_session.commit()
    _add_supplier(db_session, name="Без цен", adapter_type="no_price")
    pr = _make_part_request(db_session)
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id)
    assert summary["status"] == "no_offers"
    assert summary["offers_total"] == 1
    assert summary["offers_priced"] == 0


def test_process_defaults_to_latest_run(db_session):
    pr = _make_part_request(db_session)
    first = _search(db_session, pr)
    second = _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id)
    assert summary["run_id"] == str(second["run_id"])
    assert summary["run_id"] != str(first["run_id"])


def test_process_explicit_run_id_uses_that_run(db_session):
    pr = _make_part_request(db_session)
    first = _search(db_session, pr)
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id, run_id=first["run_id"])
    assert summary["run_id"] == str(first["run_id"])
    assert summary["offers_priced"] == 2


def test_reprocess_is_idempotent(db_session):
    pr = _make_part_request(db_session)
    _search(db_session, pr)

    PricingService(db_session).process(pr.id)
    second = PricingService(db_session).process(pr.id)

    offers = PartsSearchService(db_session).list_offers(pr.id)
    by_article = {o.article: o for o in offers}
    assert by_article["GDB2119"].customer_price == Decimal("7930.00")
    assert second["best_total_price"] == "7930.00"


# --- Read ----------------------------------------------------------------

def test_summary_reads_stored_quote(db_session):
    pr = _make_part_request(db_session)

    stored = PricingService(db_session).summary(pr.id)
    assert stored["status"] == "not_priced"

    _search(db_session, pr)
    PricingService(db_session).process(pr.id)
    stored = PricingService(db_session).summary(pr.id)
    assert stored["status"] == "priced"
    assert stored["best_total_price"] == "7930.00"


def test_process_missing_part_request_raises(db_session):
    import pytest as _pytest

    with _pytest.raises(ValueError):
        PricingService(db_session).process(uuid.uuid4())
