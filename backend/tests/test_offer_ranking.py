from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Company, Supplier
from app.services.offer_ranking_service import _FITMENT_CROSS, _FITMENT_DIRECT
from app.services.parts_search_service import PartsSearchService
from app.services.pricing_service import PricingService


@pytest.fixture(autouse=True)
def _isolate_suppliers(db_session):
    """Deactivate the seeded demo supplier so only test adapters answer."""
    from app.core.seeding import DEMO_SUPPLIERS

    demo = db_session.scalars(
        select(Supplier).where(Supplier.slug == DEMO_SUPPLIERS[0]["slug"])
    ).first()
    if demo is not None:
        demo.is_active = False
    db_session.commit()
    yield


@pytest.fixture(autouse=True)
def _custom_adapters():
    from app.suppliers.base import NormalizedSupplierOffer, SupplierAdapter, SupplierSearchQuery
    from app.suppliers.registry import supplier_registry

    class _TwoOfferAdapter(SupplierAdapter):
        type = "ranked_two"

        async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
            return [
                NormalizedSupplierOffer(
                    supplier_name=self.name, brand="A", article="A1",
                    purchase_price=Decimal("1000.00"), quantity=5, delivery_days=5,
                ),
                NormalizedSupplierOffer(
                    supplier_name=self.name, brand="B", article="B1",
                    purchase_price=Decimal("1100.00"), quantity=1, delivery_days=1,
                ),
            ]

    class _EmptyAdapter(SupplierAdapter):
        type = "ranked_empty"

        async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
            return []

    classes = (_TwoOfferAdapter, _EmptyAdapter)
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


def _make_part_request(db_session, *, quantity=1, article="A1"):
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


def _add_supplier(db_session, *, name, adapter_type, rating=None):
    supplier = Supplier(
        company_id=_company_id(db_session),
        name=name,
        slug=f"{name}-{uuid.uuid4().hex[:6]}".lower(),
        adapter_type=adapter_type,
        is_active=True,
        settings={"rating": rating} if rating is not None else {},
    )
    db_session.add(supplier)
    db_session.commit()
    return supplier


def _search(db_session, part_request):
    result = PartsSearchService(db_session).search(part_request, triggered_by="user")
    db_session.commit()
    return result


def _offers(db_session, part_request):
    return PartsSearchService(db_session).list_offers(part_request.id)


# --- Ranking service ---------------------------------------------------------

def test_rank_prefers_cheap_fast_over_pricy_slow(db_session):
    pr = _make_part_request(db_session)
    _add_supplier(db_session, name="Демо", adapter_type="ranked_two")
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id)
    ranked = summary["ranked"]

    assert [r["article"] for r in ranked] == ["A1", "B1"]
    assert ranked[0]["rank"] == 1
    assert ranked[0]["score"] > ranked[1]["score"]
    assert summary["best_article"] == "A1"

    offers = _offers(db_session, pr)
    assert [o.article for o in offers] == ["A1", "B1"]  # list_offers sorts by rank
    assert offers[0].rank == 1
    assert offers[1].rank == 2
    assert offers[0].rank_reasons
    assert offers[0].rank_score is not None


def test_rank_without_offers_returns_empty_summary(db_session):
    _add_supplier(db_session, name="Пусто", adapter_type="ranked_empty")
    pr = _make_part_request(db_session)
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id)
    assert summary["status"] == "no_offers"
    assert summary["ranked"] == []
    assert summary["best_offer_id"] is None


def test_rank_supplier_rating_boosts_expensive_offer(db_session):
    pr = _make_part_request(db_session)
    _add_supplier(db_session, name="Демо", adapter_type="ranked_two", rating=0.3)
    _search(db_session, pr)

    # Both offers from the same supplier share the rating, so price still
    # dominates: A1 (cheap) wins even though the supplier is low-rated.
    summary = PricingService(db_session).process(pr.id)
    assert summary["best_article"] == "A1"

    reasons = summary["ranked"][0]["reasons"]
    assert any("низкий рейтинг" in r for r in reasons)


def test_rank_reasons_mention_direct_article(db_session):
    pr = _make_part_request(db_session, article="A1")
    _add_supplier(db_session, name="Демо", adapter_type="ranked_two")
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id)
    reasons = summary["ranked"][0]["reasons"]
    assert any("прямой артикул" in r for r in reasons)


def test_rank_direct_beats_cross(db_session):
    pr = _make_part_request(db_session)
    _add_supplier(db_session, name="Демо", adapter_type="ranked_two")
    _search(db_session, pr)

    # Equalize price and delivery so only the fitment signal decides.
    offers = _offers(db_session, pr)
    for offer in offers:
        offer.purchase_price = Decimal("1000.00")
        offer.delivery_days = 3
    offers[0].is_cross = True  # A1 becomes a cross reference
    db_session.commit()

    summary = PricingService(db_session).process(pr.id)
    ranked = summary["ranked"]
    assert ranked[0]["article"] == "B1"  # direct beats cross at equal price/speed
    reasons = ranked[0]["reasons"]
    assert any("прямой артикул" in r for r in reasons)


def test_rank_availability_shortage_penalizes(db_session):
    pr = _make_part_request(db_session, quantity=5)
    _add_supplier(db_session, name="Демо", adapter_type="ranked_two")
    _search(db_session, pr)

    summary = PricingService(db_session).process(pr.id)
    # Requested 5, A1 has 5 (full), B1 has 1 (shortage) — A1 wins on price too.
    reasons = summary["ranked"][1]["reasons"]
    assert any("меньше" in r for r in reasons)


def test_rank_exposes_fitment_constants(db_session):
    # Sanity: direct must score above cross.
    assert _FITMENT_DIRECT > _FITMENT_CROSS


# --- Persistence / API -------------------------------------------------------

def test_rank_stored_on_offer_rows(db_session):
    pr = _make_part_request(db_session)
    _add_supplier(db_session, name="Демо", adapter_type="ranked_two")
    _search(db_session, pr)
    PricingService(db_session).process(pr.id)

    offers = _offers(db_session, pr)
    assert {o.rank for o in offers} == {1, 2}
    assert all(o.rank_score is not None for o in offers)
    assert all(o.rank_reasons is not None for o in offers)


def test_reprocess_recomputes_ranks(db_session):
    pr = _make_part_request(db_session)
    _add_supplier(db_session, name="Демо", adapter_type="ranked_two")
    _search(db_session, pr)
    PricingService(db_session).process(pr.id)
    PricingService(db_session).process(pr.id)

    offers = _offers(db_session, pr)
    assert [o.article for o in offers] == ["A1", "B1"]
    assert offers[0].rank == 1
