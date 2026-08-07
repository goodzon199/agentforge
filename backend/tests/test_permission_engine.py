from __future__ import annotations

from sqlalchemy import select

from app.core.permissions import PermissionEngine
from app.models import Company


class _Company:
    def __init__(self, settings=None):
        self.settings = settings or {}


# --- Unit: the engine --------------------------------------------------------


def test_low_allowed():
    d = PermissionEngine().evaluate(action="prepare_sales_draft", company=_Company())
    assert d.allowed is True
    assert d.requires_approval is False
    assert d.risk_level == "LOW"
    assert d.reason


def test_medium_requires_approval():
    d = PermissionEngine().evaluate(
        action="send_customer_message", resource="quote", company=_Company()
    )
    assert d.allowed is False
    assert d.requires_approval is True
    assert d.risk_level == "MEDIUM"


def test_high():
    d = PermissionEngine().evaluate(
        action="create_order", resource="quote", company=_Company()
    )
    assert d.allowed is False
    assert d.requires_approval is True
    assert d.risk_level == "HIGH"


def test_unknown_action_falls_back_to_medium():
    d = PermissionEngine().evaluate(action="nonsense_action", company=_Company())
    assert d.requires_approval is True
    assert d.risk_level == "MEDIUM"


def test_company_override_lowers_risk():
    company = _Company({"permissions": {"send_customer_message": "low"}})
    d = PermissionEngine().evaluate(
        action="send_customer_message", resource="quote", company=company
    )
    assert d.allowed is True
    assert d.risk_level == "LOW"


def test_company_override_action_resource():
    company = _Company({"permissions": {"give_discount:quote": "medium"}})
    d = PermissionEngine().evaluate(
        action="give_discount", resource="quote", company=company
    )
    assert d.requires_approval is True
    assert d.risk_level == "MEDIUM"
    d2 = PermissionEngine().evaluate(
        action="give_discount", resource="order", company=company
    )
    assert d2.risk_level == "HIGH"


def test_invalid_override_value_ignored():
    company = _Company({"permissions": {"send_customer_message": "bogus"}})
    d = PermissionEngine().evaluate(action="send_customer_message", company=company)
    assert d.risk_level == "MEDIUM"


def test_decision_contract_keys():
    d = PermissionEngine().evaluate(action="send_supplier_order", company=_Company())
    payload = d.to_dict()
    assert set(payload.keys()) == {"allowed", "requires_approval", "risk_level", "reason"}
    assert payload["risk_level"] == "HIGH"
    assert payload["reason"]


def test_effective_policies_source():
    company = _Company({"permissions": {"send_customer_message": "high"}})
    policies = {p["action"]: p for p in PermissionEngine().effective_policies(company=company)}
    assert policies["send_customer_message"]["source"] == "company"
    assert policies["send_customer_message"]["risk_level"] == "HIGH"
    assert policies["create_order"]["source"] == "default"


# --- API ---------------------------------------------------------------------


def test_api_evaluate_default(client):
    resp = client.post(
        "/api/v1/permissions/evaluate",
        json={"action": "send_customer_message", "resource": "quote"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed"] is False
    assert body["requires_approval"] is True
    assert body["risk_level"] == "MEDIUM"
    assert body["reason"]


def test_api_policies_get(client):
    resp = client.get("/api/v1/permissions/policies")
    assert resp.status_code == 200
    policies = resp.json()
    by_action = {p["action"]: p for p in policies}
    assert by_action["create_order"]["risk_level"] == "HIGH"
    assert by_action["prepare_sales_draft"]["risk_level"] == "LOW"
    assert all(p["source"] == "default" for p in policies)


def test_api_policies_put_override(client, db_session):
    resp = client.put(
        "/api/v1/permissions/policies",
        json={"permissions": {"send_customer_message": "low"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["permissions"]["send_customer_message"] == "LOW"

    resp = client.post(
        "/api/v1/permissions/evaluate",
        json={"action": "send_customer_message", "resource": "quote"},
    )
    assert resp.json()["allowed"] is True

    company = db_session.scalars(select(Company)).first()
    assert company.settings["permissions"]["send_customer_message"] == "LOW"

    resp = client.get("/api/v1/permissions/policies")
    by_action = {p["action"]: p for p in resp.json()}
    assert by_action["send_customer_message"]["source"] == "company"


def test_api_policies_invalid_value(client):
    resp = client.put(
        "/api/v1/permissions/policies",
        json={"permissions": {"send_customer_message": "bogus"}},
    )
    assert resp.status_code == 422


def test_api_evaluate_unknown_agent(client):
    import uuid as _uuid

    resp = client.post(
        "/api/v1/permissions/evaluate",
        json={"action": "send_customer_message", "agent_id": str(_uuid.uuid4())},
    )
    assert resp.status_code == 404


# --- End-to-end: override to LOW auto-sends without approval -----------------


def _make_ready_part_request(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG
    from app.models import Company
    from app.models.enums import PartRequestStatus
    from app.services.conversation_service import ConversationService
    from app.services.part_request_service import PartRequestService

    company_id = db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id
    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=company_id, name="Иван Петров")
    db_session.add(customer)
    db_session.flush()
    conversation = cs.create_conversation(
        company_id=company_id, customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    pr = PartRequestService(db_session).create(
        company_id=company_id,
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


def _priced_quote(client, db_session):
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    resp = client.post(f"/api/v1/part_requests/{pr.id}/price")
    assert resp.status_code == 200
    data = resp.json()
    return str(pr.id), data["quote_id"], str(pr.conversation_id)


def test_override_to_low_auto_sends(client, db_session):
    client.put(
        "/api/v1/permissions/policies",
        json={"permissions": {"send_customer_message": "low"}},
    )
    _, quote_id, _ = _priced_quote(client, db_session)
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message_sent"] is True
    assert body["status"] == "sent"
    assert body["approval_id"] is None
    assert body["already_executed"] is False

    detail = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    assert detail["status"] == "sent"


def test_default_send_still_requires_approval(client, db_session):
    """No override → the send is MEDIUM and goes through the manager."""
    _, quote_id, _ = _priced_quote(client, db_session)
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message_sent"] is False
    assert body["status"] == "pending"
    assert body["approval_id"] is not None

    detail = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    assert detail["status"] == "pending_approval"
