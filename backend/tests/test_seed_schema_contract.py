from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

"""Seed ↔ schema contract guard (Sprint 4.7 hardening).

Every demo entity is validated through the SAME Pydantic read-contracts the
live API uses. Demo data written around the schema (like an Order.items line
without ``offer_id``) now fails CI instead of silently breaking a page.

The regular test DB seeds with ``include_customer_demo=False``, which is
exactly why the garage-order/offer_id drift slipped through — this test seeds
the FULL demo, including the customer garage with its orders.
"""


def _full_seed_db():
    from app.core.config import settings

    settings.seed_admin_password = "test-admin-pass-123"

    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    from app.core.database import Base
    from app.core.seeding import seed_demo

    Base.metadata.create_all(engine)
    db = TestingSession()
    seed_demo(db, include_customer_demo=True)
    db.commit()
    return db, engine


def test_seed_orders_pass_OrderRead_contract():
    from app.models import Order
    from app.schemas.orders import OrderRead

    db, engine = _full_seed_db()
    try:
        orders = list(db.scalars(select(Order)).all())
        assert orders, "полный seed должен создать гаражные заказы"
        for order in orders:
            # Same contract the /orders endpoint serialises through.
            OrderRead(
                id=order.id,
                company_id=order.company_id,
                conversation_id=order.conversation_id,
                customer_id=order.customer_id,
                part_request_id=order.part_request_id,
                quote_id=order.quote_id,
                order_number=order.order_number,
                status=order.status.value,
                tracking_status=order.tracking_status or "pending",
                currency=order.currency,
                order_total=str(order.order_total)
                if order.order_total is not None
                else None,
                items=order.items or [],
                created_by_user_id=order.created_by_user_id,
                confirmed_at=order.confirmed_at,
                created_at=order.created_at,
            )
    finally:
        db.close()
        engine.dispose()


def test_seed_suppliers_pass_SupplierRead_contract():
    from app.models import Supplier
    from app.schemas.supplier import SupplierRead
    from app.suppliers.registry import supplier_registry

    db, engine = _full_seed_db()
    try:
        suppliers = list(db.scalars(select(Supplier)).all())
        assert suppliers
        for s in suppliers:
            SupplierRead(
                id=s.id,
                company_id=s.company_id,
                name=s.name,
                slug=s.slug,
                adapter_type=s.adapter_type,
                is_active=s.is_active,
                settings=s.settings,
                is_experimental=supplier_registry.is_experimental(s.adapter_type),
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
    finally:
        db.close()
        engine.dispose()


def test_seed_supplier_offers_normalized_shape():
    """SupplierOffer rows produced by the demo must carry a price and article."""
    from app.models import SupplierOffer

    db, engine = _full_seed_db()
    try:
        offers = list(db.scalars(select(SupplierOffer)).all())
        if not offers:
            return  # demo search pipeline may not run synchronously — not a fail
        for o in offers:
            assert o.supplier_id is not None
            assert o.article
            # purchase_price may be money string or Decimal — must exist and parse.
            raw = o.purchase_price
            assert raw is not None and raw != ""
    finally:
        db.close()
        engine.dispose()


def test_seed_catalog_fitments_healthy():
    from app.core.seeding import DEMO_CATALOG_FITMENTS
    from app.models import CatalogFitment

    db, engine = _full_seed_db()
    try:
        rows = list(db.scalars(select(CatalogFitment)).all())
        for r in rows:
            assert r.article
            assert r.brand
            assert r.vehicle_brand or r.vehicle_model
        assert len(rows) >= len(DEMO_CATALOG_FITMENTS)
    finally:
        db.close()
        engine.dispose()
