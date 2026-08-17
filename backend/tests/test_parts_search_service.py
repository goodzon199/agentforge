from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import SupplierOffer, SupplierSearchRun
from app.models.enums import PartRequestStatus
from app.services.parts_search_service import PartsSearchService
from app.suppliers.base import NormalizedSupplierOffer, SupplierAdapter, SupplierSearchQuery
from app.suppliers.registry import supplier_registry


@pytest.fixture(autouse=True)
def _custom_adapters():
    """Make the test-only adapter types visible to the supplier registry."""
    classes = (_FailingAdapter, _DupAdapter, _EmptyAdapter, _NoArticleAdapter)
    for cls in classes:
        supplier_registry.register(cls)
    yield
    for cls in classes:
        supplier_registry._adapters.pop(cls.type, None)


def _make_part_request(db_session, *, article="", part_name="Тормозные колодки"):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company
    from app.models.enums import PartRequestStatus as PRS
    from app.services.conversation_service import ConversationService
    from app.services.part_request_service import PartRequestService

    company = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=company.id, name="Иван Петров")
    db_session.add(customer)
    db_session.flush()
    conversation = cs.create_conversation(
        company_id=company.id, customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    pr = PartRequestService(db_session).create(
        company_id=company.id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        source_message_id=None,
        part_name=part_name,
        article=article,
        status=PRS.ready_for_search,
    )
    db_session.add(pr)
    db_session.commit()
    return pr


def _seeded_supplier(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG, DEMO_SUPPLIERS
    from app.models import Company, Supplier

    db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    return db_session.scalars(
        select(Supplier).where(Supplier.slug == DEMO_SUPPLIERS[0]["slug"])
    ).first()


def _add_supplier(db_session, *, name, adapter_type, is_active=True, settings=None):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company, Supplier

    company = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    supplier = Supplier(
        company_id=company.id,
        name=name,
        slug=f"{name}-{uuid.uuid4().hex[:6]}".lower(),
        adapter_type=adapter_type,
        is_active=is_active,
        settings=settings or {},
    )
    db_session.add(supplier)
    db_session.commit()
    return supplier


def _search(db_session, part_request, **kwargs):
    result = PartsSearchService(db_session).search(part_request, **kwargs)
    db_session.commit()
    return result


class _FailingAdapter(SupplierAdapter):
    type = "failing"

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        raise RuntimeError("supplier is down")


class _DupAdapter(SupplierAdapter):
    type = "dup"

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        return [
            NormalizedSupplierOffer(
                supplier_name=self.name, brand="B", article="X1",
                purchase_price=Decimal("7000.00"), quantity=2, delivery_days=3,
            ),
            NormalizedSupplierOffer(
                supplier_name=self.name, brand="B", article="X1",
                purchase_price=Decimal("5000.00"), quantity=1, delivery_days=1,
            ),
        ]


class _EmptyAdapter(SupplierAdapter):
    type = "empty"

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        return []


class _NoArticleAdapter(SupplierAdapter):
    type = "noarticle"

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        from app.suppliers.errors import SupplierQueryNotSupported

        raise SupplierQueryNotSupported("артикул не указан")


def test_search_creates_run_attempts_and_offers(db_session):
    pr = _make_part_request(db_session)
    result = _search(db_session, pr)

    assert result["status"] == "completed"
    assert result["offers_found"] == 2
    assert result["suppliers_succeeded"] == 1
    assert result["suppliers_failed"] == 0
    assert result["next_action"] == "pricing_parts"

    run = db_session.scalars(
        select(SupplierSearchRun).where(SupplierSearchRun.part_request_id == pr.id)
    ).first()
    assert run is not None
    assert len(run.attempts) == 1
    assert run.attempts[0].status.value == "succeeded"
    assert run.attempts[0].offers_found == 2

    offers = db_session.scalars(
        select(SupplierOffer).where(SupplierOffer.part_request_id == pr.id)
    ).all()
    assert len(offers) == 2
    prices = sorted(o.purchase_price for o in offers)
    assert prices == [Decimal("6100.00"), Decimal("6800.00")]


def test_search_filters_by_article(db_session):
    pr = _make_part_request(db_session, article="GDB2119")
    result = _search(db_session, pr)
    assert result["offers_found"] == 1
    offers = PartsSearchService(db_session).list_offers(pr.id)
    assert offers[0].article == "GDB2119"


def test_search_marks_part_request_quoted(db_session):
    pr = _make_part_request(db_session)
    _search(db_session, pr)
    db_session.refresh(pr)
    assert pr.status == PartRequestStatus.quoted


def test_search_no_offers_returns_to_ready(db_session):
    _seeded_supplier(db_session).is_active = False
    db_session.commit()
    _add_supplier(db_session, name="Пустой поставщик", adapter_type="empty")
    pr = _make_part_request(db_session)
    result = _search(db_session, pr)
    assert result["status"] == "completed"
    assert result["offers_found"] == 0
    db_session.refresh(pr)
    assert pr.status == PartRequestStatus.ready_for_search


def test_unsupported_query_supplier_is_skipped_not_failed(db_session):

    _add_supplier(db_session, name="Без артикула", adapter_type="noarticle")
    pr = _make_part_request(db_session, part_name="колодки")
    result = _search(db_session, pr)

    assert result["status"] == "completed"
    assert result["offers_found"] == 2
    assert result["suppliers_succeeded"] == 1
    assert result["suppliers_failed"] == 0

    run = db_session.scalars(
        select(SupplierSearchRun).where(SupplierSearchRun.part_request_id == pr.id)
    ).first()
    statuses = {a.status.value for a in run.attempts}
    assert "skipped" in statuses
    assert "failed" not in statuses


def test_unsupported_query_supplier_skipped_when_no_offers_at_all(db_session):

    _seeded_supplier(db_session).is_active = False
    db_session.commit()
    _add_supplier(db_session, name="Без артикула", adapter_type="noarticle")
    pr = _make_part_request(db_session, part_name="масло")
    result = _search(db_session, pr)

    assert result["status"] == "completed"
    assert result["offers_found"] == 0
    assert result["suppliers_failed"] == 0

    run = db_session.scalars(
        select(SupplierSearchRun).where(SupplierSearchRun.part_request_id == pr.id)
    ).first()
    assert {a.status.value for a in run.attempts} == {"skipped"}


def test_search_without_active_suppliers_fails_gracefully(db_session):
    _seeded_supplier(db_session).is_active = False
    db_session.commit()
    pr = _make_part_request(db_session)
    result = _search(db_session, pr)
    assert result["status"] == "failed"
    assert result["offers_found"] == 0
    db_session.refresh(pr)
    assert pr.status == PartRequestStatus.ready_for_search


def test_failing_supplier_does_not_break_the_run(db_session):
    _add_supplier(db_session, name="Сломанный поставщик", adapter_type="failing")
    pr = _make_part_request(db_session)
    result = _search(db_session, pr)

    assert result["status"] == "completed"
    assert result["offers_found"] == 2
    assert result["suppliers_succeeded"] == 1
    assert result["suppliers_failed"] == 1

    run = db_session.scalars(
        select(SupplierSearchRun).where(SupplierSearchRun.part_request_id == pr.id)
    ).first()
    failed = [a for a in run.attempts if a.status.value == "failed"]
    assert len(failed) == 1
    assert "down" in failed[0].error


def test_all_suppliers_failing_marks_run_failed(db_session):
    _seeded_supplier(db_session).is_active = False
    db_session.commit()
    _add_supplier(db_session, name="Единственный", adapter_type="failing")
    pr = _make_part_request(db_session)
    result = _search(db_session, pr)
    assert result["status"] == "failed"
    assert result["suppliers_failed"] == 1
    assert result["offers_found"] == 0


def test_dedupe_keeps_cheapest_per_article(db_session):
    _seeded_supplier(db_session).is_active = False
    db_session.commit()
    _add_supplier(db_session, name="Дублирующий", adapter_type="dup")
    pr = _make_part_request(db_session, part_name="Дубли")
    result = _search(db_session, pr)
    assert result["offers_found"] == 1
    offers = PartsSearchService(db_session).list_offers(pr.id)
    assert offers[0].purchase_price == Decimal("5000.00")


def test_repeated_search_keeps_history(db_session):
    pr = _make_part_request(db_session)
    first = _search(db_session, pr)
    second = _search(db_session, pr)

    assert first["run_id"] != second["run_id"]
    runs = PartsSearchService(db_session).list_runs(pr.id)
    assert len(runs) == 2
    assert {str(r.id) for r in runs} == {str(first["run_id"]), str(second["run_id"])}
    assert len(PartsSearchService(db_session).list_offers(pr.id)) == 4  # 2 per run


def test_result_contract_and_triggered_by(db_session):
    pr = _make_part_request(db_session)
    result = _search(db_session, pr, triggered_by="user")
    assert set(result.keys()) == {
        "run_id", "part_request_id", "status", "offers_found",
        "suppliers_succeeded", "suppliers_failed", "next_action",
    }
    run = db_session.get(SupplierSearchRun, result["run_id"])
    assert run.structured_data["triggered_by"] == "user"
    assert run.structured_data["next_action"] == "pricing_parts"


def test_list_offers_and_runs_expose_attempts(db_session):
    pr = _make_part_request(db_session)
    _search(db_session, pr, triggered_by="user")
    runs = PartsSearchService(db_session).list_runs(pr.id)
    assert len(runs) == 1
    assert runs[0].status.value == "completed"
    assert len(runs[0].attempts) == 1
