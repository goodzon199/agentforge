from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.models import Customer, Order, Vehicle
from app.services.garage_service import CustomerGarageService


def _make_customer(db_session, *, name="Тест Клиент"):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company

    company = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    customer = Customer(company_id=company.id, name=name, source="web")
    db_session.add(customer)
    db_session.commit()
    return customer


def _make_vehicle(db_session, customer, *, brand="BMW", model="X5", year=2019, vin="WBA12345"):
    service = CustomerGarageService(db_session)
    vehicle = service.add_vehicle(
        customer, brand=brand, model=model, year=year, vin=vin
    )
    db_session.commit()
    return vehicle


def _make_order(
    db_session, customer, vehicle, *, total, part_name="Фильтр", created_at=None
):
    from app.models import Conversation, PartRequest
    from app.models.enums import OrderStatus, PartRequestStatus

    conversation = Conversation(
        company_id=customer.company_id, customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    pr = PartRequest(
        company_id=customer.company_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        part_name=part_name,
        status=PartRequestStatus.completed,
    )
    if created_at is not None:
        pr.created_at = created_at
    db_session.add(pr)
    db_session.flush()
    order = Order(
        company_id=customer.company_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        part_request_id=pr.id,
        order_number=f"ORD-TEST-{uuid.uuid4().hex[:6]}",
        status=OrderStatus.paid,
        currency="RUB",
        order_total=Decimal(str(total)),
        items=[{"part_name": part_name, "article": "A1", "total_price": str(total)}],
    )
    if created_at is not None:
        order.created_at = created_at
    db_session.add(order)
    db_session.commit()
    return order


# --- Memory -----------------------------------------------------------------

def test_memory_defaults_unknown(db_session):
    customer = _make_customer(db_session)
    service = CustomerGarageService(db_session)
    memory = service.memory(customer)
    assert memory["segment"] == "unknown"
    assert memory["avg_check"] is None
    assert memory["preferences"] == {}


def test_recompute_average_check_and_segment(db_session):
    customer = _make_customer(db_session)
    bmw = _make_vehicle(db_session, customer)
    _make_order(db_session, customer, bmw, total=12000)
    _make_order(db_session, customer, bmw, total=4000)

    service = CustomerGarageService(db_session)
    memory = service.recompute_average_check(customer)
    assert memory["avg_check"] == 8000.0
    assert memory["segment"] == "middle"
    assert customer.memory["avg_check"] == 8000.0


def test_segment_premium_above_border(db_session):
    customer = _make_customer(db_session)
    bmw = _make_vehicle(db_session, customer)
    _make_order(db_session, customer, bmw, total=25000)

    memory = CustomerGarageService(db_session).recompute_average_check(customer)
    assert memory["segment"] == "premium"


def test_segment_economy_below_border(db_session):
    customer = _make_customer(db_session)
    bmw = _make_vehicle(db_session, customer)
    _make_order(db_session, customer, bmw, total=3000)

    memory = CustomerGarageService(db_session).recompute_average_check(customer)
    assert memory["segment"] == "economy"


def test_cancelled_orders_excluded_from_average(db_session):
    from app.models.enums import OrderStatus

    customer = _make_customer(db_session)
    bmw = _make_vehicle(db_session, customer)
    _make_order(db_session, customer, bmw, total=10000)
    order = _make_order(db_session, customer, bmw, total=30000)
    order.status = OrderStatus.cancelled
    db_session.commit()

    memory = CustomerGarageService(db_session).recompute_average_check(customer)
    assert memory["avg_check"] == 10000.0


def test_set_preferences_merges(db_session):
    customer = _make_customer(db_session)
    service = CustomerGarageService(db_session)
    service.set_preferences(customer, {"segment": "premium"})
    service.set_preferences(customer, {"note": "любит масло 5W30"})

    memory = service.memory(customer)
    assert memory["preferences"] == {
        "segment": "premium",
        "note": "любит масло 5W30",
    }


# --- Garage -----------------------------------------------------------------

def test_list_vehicles_and_garage_snapshot(db_session):
    customer = _make_customer(db_session)
    _make_vehicle(db_session, customer, brand="BMW", model="X5")
    _make_vehicle(db_session, customer, brand="Toyota", model="Camry")

    service = CustomerGarageService(db_session)
    assert len(service.list_vehicles(customer)) == 2

    snapshot = service.garage(customer)
    assert snapshot["customer_id"] == str(customer.id)
    assert len(snapshot["vehicles"]) == 2
    labels = [v["vehicle"]["brand"] for v in snapshot["vehicles"]]
    assert set(labels) == {"BMW", "Toyota"}


def test_purchase_history_per_vehicle(db_session):
    customer = _make_customer(db_session)
    bmw = _make_vehicle(db_session, customer, brand="BMW", model="X5")
    camry = _make_vehicle(db_session, customer, brand="Toyota", model="Camry")
    _make_order(db_session, customer, bmw, total=15000, part_name="Воздушный фильтр")
    _make_order(db_session, customer, camry, total=2000, part_name="Масляный фильтр")

    service = CustomerGarageService(db_session)
    bmw_history = service.purchase_history(bmw)
    camry_history = service.purchase_history(camry)
    assert len(bmw_history) == 1
    assert bmw_history[0]["part_name"] == "Воздушный фильтр"
    assert bmw_history[0]["total_price"] == "15000.00"
    assert camry_history[0]["part_name"] == "Масляный фильтр"


def test_default_vehicle_single(db_session):
    customer = _make_customer(db_session)
    bmw = _make_vehicle(db_session, customer)
    assert CustomerGarageService(db_session).default_vehicle(customer).id == bmw.id


def test_default_vehicle_prefers_recently_used(db_session):
    from datetime import UTC, datetime

    customer = _make_customer(db_session)
    bmw = _make_vehicle(db_session, customer, brand="BMW", model="X5")
    camry = _make_vehicle(db_session, customer, brand="Toyota", model="Camry")
    # Last request was for the BMW.
    _make_order(
        db_session,
        customer,
        camry,
        total=2000,
        part_name="Масло",
        created_at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
    )
    _make_order(
        db_session,
        customer,
        bmw,
        total=15000,
        part_name="Фильтр",
        created_at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=UTC),
    )

    default = CustomerGarageService(db_session).default_vehicle(customer)
    assert default.brand == "BMW"


def test_default_vehicle_empty_garage(db_session):
    customer = _make_customer(db_session)
    assert CustomerGarageService(db_session).default_vehicle(customer) is None


def test_update_and_delete_vehicle(db_session):
    customer = _make_customer(db_session)
    bmw = _make_vehicle(db_session, customer, brand="BMW", model="X5")
    service = CustomerGarageService(db_session)
    service.update_vehicle(bmw, year=2020, model="X5 M")
    db_session.commit()
    assert bmw.year == 2020
    assert bmw.model == "X5 M"

    service.delete_vehicle(bmw)
    db_session.commit()
    assert db_session.get(Vehicle, bmw.id) is None
    assert service.list_vehicles(customer) == []


def test_garage_seeded_demo_customer_exists(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG, _seed_customer_garage
    from app.models import Company

    company = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first()
    assert _seed_customer_garage(db_session, company) is True
    ivan = db_session.scalars(
        select(Customer).where(
            Customer.company_id == company.id, Customer.source == "garage-demo"
        )
    ).first()
    assert ivan is not None
    assert ivan.name == "Иван"

    service = CustomerGarageService(db_session)
    vehicles = service.list_vehicles(ivan)
    assert {v.brand for v in vehicles} == {"BMW", "Toyota"}
    history = sum(len(service.purchase_history(v)) for v in vehicles)
    assert history >= 5
    memory = service.memory(ivan)
    assert memory["avg_check"] is not None
