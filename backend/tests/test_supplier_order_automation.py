from __future__ import annotations

import uuid

from sqlalchemy import select


def _company_id(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company

    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id


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


def _sent_quote(client, db_session) -> tuple[str, str, str]:
    """Price + send + approve -> (quote_id, conversation_id, draft_text)."""
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    price = client.post(f"/api/v1/part_requests/{pr.id}/price").json()
    quote_id = price["quote_id"]
    conversation_id = str(pr.conversation_id)

    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    send = client.post(
        f"/api/v1/quotes/{quote_id}/send", json={"message": draft["ai_draft"]}
    ).json()
    approve = client.post(f"/api/v1/approvals/{send['approval_id']}/approve")
    assert approve.status_code == 200
    return quote_id, conversation_id, draft["ai_draft"]


def _converted_order_id(client, db_session) -> str:
    quote_id, _conversation_id, _ = _sent_quote(client, db_session)
    data = client.post(f"/api/v1/quotes/{quote_id}/convert").json()
    return data["order_id"]


def _purchases(client, order_id):
    return client.get(f"/api/v1/supplier-orders?order_id={order_id}").json()


def _send_actions(client):
    return [
        a
        for a in client.get("/api/v1/actions").json()
        if a["action_type"] == "send_supplier_order"
    ]


def test_order_creation_auto_requests_purchase(client, db_session):
    order_id = _converted_order_id(client, db_session)

    purchases = _purchases(client, order_id)
    assert len(purchases) == 1
    purchase = purchases[0]
    assert purchase["action_type"] == "send_supplier_order"
    assert purchase["status"] == "pending"
    assert purchase["risk_level"] == "HIGH"
    assert purchase["supplier_name"] == "АвтоТорг (демо)"
    assert purchase["order_id"] == order_id
    assert purchase["external_order_id"] is None

    # The order stays `new` until the purchase is approved by a manager.
    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["status"] == "new"

    # send_supplier_order is audited as a HIGH pending action.
    sends = _send_actions(client)
    assert len(sends) == 1
    assert sends[0]["risk_level"] == "HIGH"
    assert sends[0]["status"] == "pending"


def test_request_purchase_idempotent(client, db_session):
    order_id = _converted_order_id(client, db_session)
    again = client.post("/api/v1/supplier-orders", json={"order_id": order_id})
    assert again.status_code == 200
    assert len(again.json()) == 1
    assert len(_send_actions(client)) == 1


def test_approve_places_external_order(client, db_session):
    order_id = _converted_order_id(client, db_session)
    approval_id = _purchases(client, order_id)[0]["approval_id"]

    resp = client.post(f"/api/v1/supplier-orders/{approval_id}/approve")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["already_approved"] is False
    assert data["external_order_id"].startswith("EXT-")
    assert data["supplier_status"] == "accepted"
    assert data["order_status"] == "confirmed"

    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["status"] == "confirmed"

    from app.models import SupplierFulfillment

    fulfillments = db_session.scalars(
        select(SupplierFulfillment).where(
            SupplierFulfillment.order_id == uuid.UUID(order_id)
        )
    ).unique().all()
    assert len(fulfillments) == 2
    for fulfillment in fulfillments:
        assert fulfillment.external_order_id == data["external_order_id"]
        assert fulfillment.supplier_status == "accepted"
        assert fulfillment.ordered_at is not None

    sends = _send_actions(client)
    assert len(sends) == 1
    assert sends[0]["status"] == "executed"


def test_approve_idempotent(client, db_session):
    order_id = _converted_order_id(client, db_session)
    approval_id = _purchases(client, order_id)[0]["approval_id"]

    first = client.post(f"/api/v1/supplier-orders/{approval_id}/approve").json()
    again = client.post(f"/api/v1/supplier-orders/{approval_id}/approve").json()
    assert again["already_approved"] is True
    assert again["external_order_id"] == first["external_order_id"]
    assert len(_send_actions(client)) == 1


def test_reject_cancels_purchase(client, db_session):
    order_id = _converted_order_id(client, db_session)
    approval_id = _purchases(client, order_id)[0]["approval_id"]

    resp = client.post(
        f"/api/v1/supplier-orders/{approval_id}/reject",
        json={"rejection_reason": "Слишком дорого"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"

    purchases = _purchases(client, order_id)
    assert purchases[0]["status"] == "rejected"
    assert purchases[0]["external_order_id"] is None
    assert purchases[0]["rejection_reason"] == "Слишком дорого"

    # No money was spent: the order is still `new`.
    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["status"] == "new"

    sends = _send_actions(client)
    assert len(sends) == 1
    assert sends[0]["status"] == "cancelled"


def test_approve_manager_only(client, db_session):
    from app.core.config import settings
    from app.models import User

    order_id = _converted_order_id(client, db_session)
    approval_id = _purchases(client, order_id)[0]["approval_id"]

    admin = db_session.scalars(
        select(User).where(User.email == settings.seed_admin_email)
    ).first()
    admin.is_superuser = False
    db_session.commit()

    resp = client.post(f"/api/v1/supplier-orders/{approval_id}/approve")
    assert resp.status_code == 403
    admin.is_superuser = True
    db_session.commit()


def test_purchase_scoped_to_company(client, db_session):
    from app.models import Company, Order

    other = Company(name="Другая компания", slug="other-company-4-5")
    db_session.add(other)
    db_session.commit()
    order = Order(
        company_id=other.id,
        conversation_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        part_request_id=uuid.uuid4(),
        order_number="ORD-OTHER-45",
        items=[],
    )
    db_session.add(order)
    db_session.commit()

    # A manager of the demo company cannot touch another company's order.
    resp = client.post(
        "/api/v1/supplier-orders", json={"order_id": str(order.id)}
    )
    assert resp.status_code == 403
    assert _purchases(client, order.id) == []


def test_supplier_without_order_support_fails_gracefully(monkeypatch, client, db_session):
    """A provider that only searches must never crash the approval flow."""
    order_id = _converted_order_id(client, db_session)
    approval_id = _purchases(client, order_id)[0]["approval_id"]

    # Swap in a read-only provider only for the purchase step — the search
    # must still have run against the real mock to build the order.
    from app.services.supplier_service import SupplierService
    from app.suppliers.base import SupplierAdapter, SupplierSearchQuery

    class ReadOnlyAdapter(SupplierAdapter):
        type = "readonly-test"

        async def search(self, query: SupplierSearchQuery) -> list:
            return []

    monkeypatch.setattr(
        SupplierService,
        "adapter_for",
        lambda self, supplier: ReadOnlyAdapter(name=supplier.name),
    )

    resp = client.post(f"/api/v1/supplier-orders/{approval_id}/approve")
    assert resp.status_code == 409

    # No external order, and the request stays pending so it can be retried
    # (or the supplier swapped for one that supports ordering).
    purchase = _purchases(client, order_id)[0]
    assert purchase["status"] == "pending"
    assert purchase["external_order_id"] is None
    order = client.get(f"/api/v1/orders/{order_id}").json()
    assert order["status"] == "new"
