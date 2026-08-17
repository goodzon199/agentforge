from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    Company,
    Order,
    PartReturn,
    Supplier,
    SupplierFulfillment,
    SupplierOffer,
    SupplierSearchAttempt,
    SupplierSearchRun,
)
from app.models.enums import (
    OrderStatus,
    PartRequestStatus,
    SupplierAttemptStatus,
    SupplierSearchStatus,
)
from app.services.supplier_reliability_service import SupplierReliabilityService


def _company_id(db_session):
    return db_session.scalars(
        select(Company).where(Company.slug == "demo")
    ).first().id


def _supplier(db_session):
    return db_session.scalars(select(Supplier)).first()


def _pr(db_session, *, article="0345"):
    from app.services.conversation_service import ConversationService

    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=_company_id(db_session), name="Иван")
    db_session.add(customer)
    db_session.flush()
    conversation = cs.create_conversation(
        company_id=_company_id(db_session), customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    from app.services.part_request_service import PartRequestService

    pr = PartRequestService(db_session).create(
        company_id=_company_id(db_session),
        conversation_id=conversation.id,
        customer_id=customer.id,
        source_message_id=None,
        part_name="Колодки",
        article=article,
        status=PartRequestStatus.completed,
    )
    db_session.add(pr)
    db_session.flush()
    return pr, conversation


def _run(db_session, pr):
    run = SupplierSearchRun(
        part_request_id=pr.id,
        status=SupplierSearchStatus.completed,
        offers_found=1,
    )
    db_session.add(run)
    db_session.flush()
    return run


def _attempt(db_session, supplier, run, *, status=SupplierAttemptStatus.succeeded, latency_ms=300):
    db_session.add(
        SupplierSearchAttempt(
            search_run_id=run.id,
            supplier_id=supplier.id,
            status=status,
            offers_found=1 if status == SupplierAttemptStatus.succeeded else 0,
            error="" if status == SupplierAttemptStatus.succeeded else "boom",
            latency_ms=latency_ms,
        )
    )


def _offer(db_session, supplier, pr, run, *, price=1000, days=3):
    offer = SupplierOffer(
        part_request_id=pr.id,
        search_run_id=run.id,
        supplier_id=supplier.id,
        brand="BREMBO",
        article="0345",
        part_name="Колодки",
        purchase_price=Decimal(price),
        quantity=1,
        delivery_days=days,
        customer_price=Decimal("1500"),
        total_price=Decimal("1500"),
    )
    db_session.add(offer)
    db_session.flush()
    return offer


def _order(db_session, supplier, offer, *, status=OrderStatus.confirmed):
    from app.models import PartRequest

    pr = db_session.get(PartRequest, offer.part_request_id)
    order = Order(
        company_id=_company_id(db_session),
        conversation_id=pr.conversation_id,
        customer_id=pr.customer_id,
        part_request_id=offer.part_request_id,
        order_number=f"ORD-T-{uuid.uuid4().hex[:6]}",
        status=status,
        items=[
            {
                "offer_id": str(offer.id),
                "article": "0345",
                "brand": "BREMBO",
                "quantity_available": 1,
                "delivery_days": 3,
            }
        ],
    )
    db_session.add(order)
    db_session.flush()
    return order


# --- compute() scoreboard --------------------------------------------------


def test_empty_supplier_is_neutral(db_session):
    supplier = _supplier(db_session)
    result = SupplierReliabilityService(db_session).compute(supplier)

    assert result.rating_source == "auto"
    assert result.rating == 0.5  # neutral prior: nothing observed yet
    assert result.orders_total == 0
    assert result.attempts_total == 0
    assert result.confirmation_rate is None
    assert result.api_availability is None


def test_compute_collects_api_metrics(db_session):
    supplier = _supplier(db_session)
    pr, _ = _pr(db_session)
    run = _run(db_session, pr)
    for i in range(10):
        _attempt(
            db_session,
            supplier,
            run,
            status=SupplierAttemptStatus.succeeded,
            latency_ms=100 + i * 10,
        )
    _attempt(db_session, supplier, run, status=SupplierAttemptStatus.failed, latency_ms=None)
    db_session.commit()

    result = SupplierReliabilityService(db_session).compute(supplier)
    assert result.attempts_total == 11
    assert result.attempts_failed == 1
    assert result.api_availability == 90.9
    assert result.api_avg_latency_ms == 145.0
    assert result.api_p95_latency_ms is not None
    # availability drags the api score, and a good api raises the composite.
    assert result.rating > 0.5


def test_compute_collects_order_metrics(db_session):
    supplier = _supplier(db_session)
    pr, _ = _pr(db_session)
    run = _run(db_session, pr)
    offer = _offer(db_session, supplier, pr, run)
    _order(db_session, supplier, offer, status=OrderStatus.confirmed)
    _order(db_session, supplier, offer, status=OrderStatus.paid)
    _order(db_session, supplier, offer, status=OrderStatus.cancelled)
    db_session.commit()

    result = SupplierReliabilityService(db_session).compute(supplier)
    assert result.orders_total == 3
    assert result.confirmed == 2
    assert result.cancelled == 1
    assert result.confirmation_rate == 66.7
    assert result.cancellation_rate == 33.3


def test_compute_collects_fulfillment_metrics(db_session):
    supplier = _supplier(db_session)
    pr, _ = _pr(db_session)
    run = _run(db_session, pr)
    offer = _offer(db_session, supplier, pr, run, price=1000, days=3)

    def add(*, promised_price, actual_price, promised_days, actual_days, ordered, delivered):
        db_session.add(
            SupplierFulfillment(
                company_id=_company_id(db_session),
                supplier_id=supplier.id,
                order_id=None,
                offer_id=offer.id,
                article="0345",
                brand="BREMBO",
                promised_purchase_price=promised_price,
                promised_delivery_days=promised_days,
                quantity_ordered=ordered,
                actual_purchase_price=actual_price,
                actual_delivery_days=actual_days,
                quantity_delivered=delivered,
                status="delivered",
            )
        )

    add(promised_price=1000, actual_price=1000, promised_days=3, actual_days=2, ordered=1, delivered=1)   # on-time, same price
    add(promised_price=1000, actual_price=1200, promised_days=3, actual_days=5, ordered=2, delivered=1)   # late + price change + short
    add(promised_price=500, actual_price=500, promised_days=2, actual_days=2, ordered=1, delivered=1)      # on-time
    db_session.commit()

    result = SupplierReliabilityService(db_session).compute(supplier)
    assert result.fulfillments_total == 3
    assert result.fulfillments_recorded == 3
    assert result.on_time_delivery == 66.7
    assert result.price_change_rate == 33.3
    assert result.under_delivery_rate == 33.3


def test_compute_collects_returns(db_session):
    supplier = _supplier(db_session)
    pr, _ = _pr(db_session)
    db_session.add(
        PartReturn(
            company_id=_company_id(db_session),
            supplier_id=supplier.id,
            part_request_id=pr.id,
            article="0345",
            brand="BREMBO",
            reason="брак",
            status="returned",
            returned_at=datetime.now(UTC),
        )
    )
    # A return without supplier attribution must NOT count for this supplier.
    db_session.add(
        PartReturn(
            company_id=_company_id(db_session),
            supplier_id=None,
            part_request_id=pr.id,
            article="0345",
            brand="BREMBO",
            reason="не мой возврат",
            status="returned",
        )
    )
    db_session.commit()

    result = SupplierReliabilityService(db_session).compute(supplier)
    assert result.returns_total == 1


# --- refresh(): rating is persisted as auto --------------------------------


def test_refresh_persists_auto_rating(db_session):
    supplier = _supplier(db_session)
    supplier.settings = {"rating": 0.95, "note": "старая ручная оценка"}
    db_session.commit()

    result = SupplierReliabilityService(db_session).refresh(supplier)

    assert result.rating == 0.5  # no data -> neutral, overrides the seed
    assert supplier.settings["rating"] == 0.5
    assert supplier.settings["rating_source"] == "auto"


def test_good_history_raises_rating(db_session):
    supplier = _supplier(db_session)
    pr, _ = _pr(db_session)
    run = _run(db_session, pr)
    for _ in range(20):
        _attempt(db_session, supplier, run, status=SupplierAttemptStatus.succeeded, latency_ms=150)
    offer = _offer(db_session, supplier, pr, run)
    for _ in range(10):
        _order(db_session, supplier, offer, status=OrderStatus.confirmed)
    for _ in range(20):
        db_session.add(
            SupplierFulfillment(
                company_id=_company_id(db_session),
                supplier_id=supplier.id,
                order_id=None,
                offer_id=offer.id,
                article="0345",
                brand="BREMBO",
                promised_purchase_price=Decimal("1000"),
                promised_delivery_days=3,
                quantity_ordered=1,
                actual_purchase_price=Decimal("1000"),
                actual_delivery_days=2,
                quantity_delivered=1,
                status="delivered",
            )
        )
    db_session.commit()

    result = SupplierReliabilityService(db_session).refresh(supplier)
    assert result.rating > 0.9
    assert supplier.settings["rating"] > 0.9


def test_recompute_all_commits(db_session):
    supplier = _supplier(db_session)
    results = SupplierReliabilityService(db_session).recompute_all(_company_id(db_session))
    assert len(results) == 1
    assert results[0].supplier_id == str(supplier.id)


# --- record_fulfillments_for_order ------------------------------------------


def test_order_creation_snapshots_fulfillments(db_session):
    supplier = _supplier(db_session)
    pr, _ = _pr(db_session)
    run = _run(db_session, pr)
    offer = _offer(db_session, supplier, pr, run, price=1234, days=5)
    order = _order(db_session, supplier, offer)
    db_session.commit()

    service = SupplierReliabilityService(db_session)
    service.record_fulfillments_for_order(order)
    db_session.commit()

    rows = db_session.scalars(
        select(SupplierFulfillment).where(SupplierFulfillment.order_id == order.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].supplier_id == supplier.id
    assert rows[0].promised_purchase_price == Decimal("1234")
    assert rows[0].promised_delivery_days == 5
    # The rating was refreshed as a side effect of snapshotting.
    assert supplier.settings["rating_source"] == "auto"


# --- record_fulfillment_actual ----------------------------------------------


def test_record_actual_by_order_and_article(db_session):
    supplier = _supplier(db_session)
    pr, _ = _pr(db_session)
    run = _run(db_session, pr)
    offer = _offer(db_session, supplier, pr, run, price=1000, days=3)
    order = _order(db_session, supplier, offer)
    service = SupplierReliabilityService(db_session)
    service.record_fulfillments_for_order(order)
    db_session.commit()

    fulfillment = service.record_fulfillment_actual(
        supplier,
        order_id=order.id,
        article="0345",
        actual_purchase_price=Decimal("1300"),
        actual_delivery_days=7,
        quantity_delivered=1,
        status="partial",
        delivered_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.commit()

    assert fulfillment is not None
    assert fulfillment.status == "partial"
    assert fulfillment.actual_purchase_price == Decimal("1300")
    assert fulfillment.actual_delivery_days == 7


def test_record_actual_missing_line_returns_none(db_session):
    supplier = _supplier(db_session)
    result = SupplierReliabilityService(db_session).record_fulfillment_actual(
        supplier, order_id=uuid.uuid4(), article="NOPE"
    )
    assert result is None


# --- SupplierService: manual rating becomes a stale seed ---------------------


def test_create_supplier_rating_is_seed_not_truth(client, db_session):
    resp = client.post(
        "/api/v1/suppliers",
        json={
            "company_id": str(_company_id(db_session)),
            "name": "Новый поставщик",
            "settings": {"rating": 0.95},
        },
    )
    assert resp.status_code == 201
    settings = resp.json()["settings"]
    assert settings["rating"] == 0.95
    assert settings["rating_source"] == "stale"


# --- API endpoints -----------------------------------------------------------


def test_reliability_endpoint(client, db_session):
    supplier = _supplier(db_session)
    resp = client.get(f"/api/v1/suppliers/{supplier.id}/reliability")
    assert resp.status_code == 200
    data = resp.json()
    assert data["supplier_id"] == str(supplier.id)
    assert data["rating_source"] == "auto"
    assert data["attempts_total"] == 0


def test_recompute_endpoint(client, db_session):
    supplier = _supplier(db_session)
    resp = client.post(f"/api/v1/suppliers/{supplier.id}/recompute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rating_source"] == "auto"
    assert data["rating"] == 0.5
    # persisted
    db_session.refresh(supplier)
    assert supplier.settings["rating"] == 0.5


def test_recompute_all_endpoint(client, db_session):
    resp = client.post("/api/v1/suppliers/recompute")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_fulfillments_list_and_record_endpoints(client, db_session):
    supplier = _supplier(db_session)
    pr, _ = _pr(db_session)
    run = _run(db_session, pr)
    offer = _offer(db_session, supplier, pr, run, price=1000, days=3)
    order = _order(db_session, supplier, offer)
    from app.services.supplier_reliability_service import SupplierReliabilityService

    SupplierReliabilityService(db_session).record_fulfillments_for_order(order)
    db_session.commit()

    resp = client.get(f"/api/v1/suppliers/{supplier.id}/fulfillments")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    fulfillments = db_session.scalars(
        select(SupplierFulfillment).where(SupplierFulfillment.supplier_id == supplier.id)
    ).all()
    fid = str(fulfillments[0].id)
    resp = client.post(
        f"/api/v1/suppliers/{supplier.id}/fulfillments",
        json={
            "fulfillment_id": fid,
            "actual_purchase_price": "1400",
            "actual_delivery_days": 9,
            "quantity_delivered": 1,
            "status": "cancelled",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["actual_purchase_price"] == "1400.00"
    assert data["status"] == "cancelled"


def test_fulfillment_record_404(client, db_session):
    supplier = _supplier(db_session)
    resp = client.post(
        f"/api/v1/suppliers/{supplier.id}/fulfillments",
        json={"order_id": str(uuid.uuid4()), "article": "NOPE"},
    )
    assert resp.status_code == 404


def test_reliability_404(client, db_session):
    resp = client.get(f"/api/v1/suppliers/{uuid.uuid4()}/reliability")
    assert resp.status_code == 404
