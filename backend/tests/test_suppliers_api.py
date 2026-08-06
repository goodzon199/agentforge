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


def test_list_suppliers_returns_seeded_demo(client, db_session):
    resp = client.get("/api/v1/suppliers")
    assert resp.status_code == 200
    suppliers = resp.json()
    assert len(suppliers) == 1
    assert suppliers[0]["adapter_type"] == "mock"
    assert suppliers[0]["is_active"] is True


def test_create_supplier(client, db_session):
    resp = client.post(
        "/api/v1/suppliers",
        json={
            "company_id": str(_company_id(db_session)),
            "name": "Каталог CSV",
            "adapter_type": "csv",
            "settings": {"file_path": "/data/feed.csv"},
        },
    )
    assert resp.status_code == 201
    supplier = resp.json()
    assert supplier["adapter_type"] == "csv"
    assert supplier["settings"]["file_path"] == "/data/feed.csv"
    assert supplier["slug"]

    assert len(client.get("/api/v1/suppliers").json()) == 2


def test_create_supplier_unknown_adapter_422(client, db_session):
    resp = client.post(
        "/api/v1/suppliers",
        json={"company_id": str(_company_id(db_session)), "name": "X", "adapter_type": "nope"},
    )
    assert resp.status_code == 422


def test_patch_supplier(client, db_session):
    supplier_id = _seeded_supplier_id(client, db_session)
    resp = client.patch(
        f"/api/v1/suppliers/{supplier_id}",
        json={"is_active": False, "settings": {"note": "выключен"}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_active"] is False
    assert data["settings"]["note"] == "выключен"


def test_patch_supplier_404(client, db_session):
    resp = client.patch(
        f"/api/v1/suppliers/{uuid.uuid4()}", json={"is_active": False}
    )
    assert resp.status_code == 404


def test_test_supplier(client, db_session):
    supplier_id = _seeded_supplier_id(client, db_session)
    resp = client.post(f"/api/v1/suppliers/{supplier_id}/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["offers_found"] >= 1
    assert data["latency_ms"] is not None


def test_test_supplier_404(client, db_session):
    resp = client.post(f"/api/v1/suppliers/{uuid.uuid4()}/test")
    assert resp.status_code == 404


def test_offers_empty_before_search(client, db_session):
    pr = _make_ready_part_request(db_session)
    resp = client.get(f"/api/v1/part_requests/{pr.id}/offers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_creates_run_and_offers(client, db_session):
    pr = _make_ready_part_request(db_session)
    resp = client.post(f"/api/v1/part_requests/{pr.id}/search")
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "completed"
    assert result["offers_found"] == 2
    assert result["suppliers_succeeded"] == 1
    assert result["next_action"] == "pricing_parts"

    offers = client.get(f"/api/v1/part_requests/{pr.id}/offers").json()
    assert len(offers) == 2
    assert {o["article"] for o in offers} == {"P06089", "GDB2119"}
    assert {o["purchase_price"] for o in offers} == {"6100.00", "6800.00"}
    assert all(o["supplier_name"] for o in offers)

    runs = client.get(f"/api/v1/part_requests/{pr.id}/search-runs").json()
    assert len(runs) == 1
    assert runs[0]["status"] == "completed"
    assert runs[0]["attempts"][0]["status"] == "succeeded"
    assert runs[0]["structured_data"]["triggered_by"] == "user"


def test_repeated_search_keeps_history(client, db_session):
    pr = _make_ready_part_request(db_session)
    first = client.post(f"/api/v1/part_requests/{pr.id}/search").json()
    second = client.post(f"/api/v1/part_requests/{pr.id}/search").json()
    assert first["run_id"] != second["run_id"]
    runs = client.get(f"/api/v1/part_requests/{pr.id}/search-runs").json()
    assert len(runs) == 2


def test_search_without_active_suppliers(client, db_session):
    supplier_id = _seeded_supplier_id(client, db_session)
    client.patch(f"/api/v1/suppliers/{supplier_id}", json={"is_active": False})
    pr = _make_ready_part_request(db_session)
    resp = client.post(f"/api/v1/part_requests/{pr.id}/search")
    assert resp.status_code == 200
    result = resp.json()
    assert result["status"] == "failed"
    assert result["offers_found"] == 0

    detail = client.get(f"/api/v1/part_requests/{pr.id}").json()
    assert detail["status"] == "ready_for_search"


def test_search_part_request_404(client, db_session):
    resp = client.post(f"/api/v1/part_requests/{uuid.uuid4()}/search")
    assert resp.status_code == 404


def test_offers_search_runs_404(client, db_session):
    missing = str(uuid.uuid4())
    assert client.get(f"/api/v1/part_requests/{missing}/offers").status_code == 404
    assert client.get(f"/api/v1/part_requests/{missing}/search-runs").status_code == 404
