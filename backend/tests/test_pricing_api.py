from __future__ import annotations

import uuid

from sqlalchemy import select


def _company_id(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company

    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id


def _seeded_supplier_id(client, db_session):
    return client.get("/api/v1/suppliers").json()[0]["id"]


def _make_ready_part_request(db_session):
    from app.models.enums import PartRequestStatus
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
        article="",
        status=PartRequestStatus.ready_for_search,
    )
    db_session.add(pr)
    db_session.commit()
    return pr


def _searched_part_request_id(client, db_session) -> str:
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    return str(pr.id)


def test_price_endpoint_returns_quote(client, db_session):
    part_request_id = _searched_part_request_id(client, db_session)

    resp = client.post(f"/api/v1/part_requests/{part_request_id}/price")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "priced"
    assert data["best_article"] == "GDB2119"
    assert data["best_unit_price"] == "7930.00"
    assert data["best_total_price"] == "7930.00"
    assert data["margin_percent"] == 30.0
    assert data["offers_priced"] == 2

    offers = client.get(f"/api/v1/part_requests/{part_request_id}/offers").json()
    by_article = {o["article"]: o for o in offers}
    assert by_article["GDB2119"]["customer_price"] == "7930.00"
    assert by_article["P06089"]["customer_price"] == "8840.00"
    assert by_article["GDB2119"]["total_price"] == "7930.00"
    assert by_article["GDB2119"]["margin_percent"] == "30.00"


def test_quote_before_pricing_is_not_priced(client, db_session):
    part_request_id = _searched_part_request_id(client, db_session)
    resp = client.get(f"/api/v1/part_requests/{part_request_id}/quote")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "not_priced"
    assert data["offers_priced"] == 0


def test_quote_after_pricing(client, db_session):
    part_request_id = _searched_part_request_id(client, db_session)
    client.post(f"/api/v1/part_requests/{part_request_id}/price")
    resp = client.get(f"/api/v1/part_requests/{part_request_id}/quote")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "priced"
    assert data["best_total_price"] == "7930.00"


def test_price_with_no_offers_returns_no_offers(client, db_session):
    supplier_id = _seeded_supplier_id(client, db_session)
    client.patch(f"/api/v1/suppliers/{supplier_id}", json={"is_active": False})
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")

    resp = client.post(f"/api/v1/part_requests/{pr.id}/price")
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_offers"


def test_price_404(client, db_session):
    resp = client.post(f"/api/v1/part_requests/{uuid.uuid4()}/price")
    assert resp.status_code == 404


def test_quote_404(client, db_session):
    resp = client.get(f"/api/v1/part_requests/{uuid.uuid4()}/quote")
    assert resp.status_code == 404
