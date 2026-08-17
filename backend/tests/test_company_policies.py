from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.policies import DEFAULT_POLICIES, merge_policy
from app.models import Company, Supplier
from app.services.company_policy_service import CompanyPolicyService
from app.services.parts_search_service import PartsSearchService
from app.services.pricing_service import PricingService

# --- Unit: merge -------------------------------------------------------------


def test_merge_policy_keeps_defaults_for_missing_keys():
    merged = merge_policy(DEFAULT_POLICIES["pricing"], {"min_margin_percent": 15})
    assert merged["min_margin_percent"] == 15
    assert merged["rounding"] == 0.01
    assert merged["allow_discounts"] is False


def test_merge_policy_merges_nested_dicts():
    merged = merge_policy(
        DEFAULT_POLICIES["supplier"], {"favorite_brands": ["TRW"]}
    )
    assert merged["favorite_brands"] == ["TRW"]
    assert merged["blocked_brands"] == []


# --- Service ----------------------------------------------------------------


def test_policy_returns_defaults_without_row(db_session):
    company_id = db_session.scalars(select(Company)).first().id
    service = CompanyPolicyService(db_session)
    sales = service.policy(company_id, "sales")
    assert sales == DEFAULT_POLICIES["sales"]
    effective = service.effective(company_id)
    assert set(effective.keys()) == {"pricing", "supplier", "approval", "sales", "security"}


def test_update_partial_merges_other_keys(db_session):
    company_id = db_session.scalars(select(Company)).first().id
    service = CompanyPolicyService(db_session)
    service.update(company_id, pricing={"min_margin_percent": 20})
    pricing = service.policy(company_id, "pricing")
    assert pricing["min_margin_percent"] == 20
    assert pricing["rounding"] == 0.01  # untouched
    assert pricing["markups"] == {}
    # second partial update keeps the first
    service.update(company_id, pricing={"rounding": 50})
    pricing = service.policy(company_id, "pricing")
    assert pricing["min_margin_percent"] == 20
    assert pricing["rounding"] == 50


def test_security_policy_mirrors_to_settings_permissions(db_session):
    company = db_session.scalars(select(Company)).first()
    CompanyPolicyService(db_session).update(
        company.id, security={"permissions": {"send_customer_message": "low"}}
    )
    db_session.refresh(company)
    assert company.settings["permissions"]["send_customer_message"] == "LOW"

    # clearing permissions removes the key
    CompanyPolicyService(db_session).update(company.id, security={"permissions": {}})
    db_session.refresh(company)
    assert "permissions" not in (company.settings or {})


def test_update_non_dict_payload_raises(db_session):
    company_id = db_session.scalars(select(Company)).first().id
    with pytest.raises(TypeError):
        CompanyPolicyService(db_session).update(company_id, pricing="oops")  # type: ignore[arg-type]


# --- Pricing policy ---------------------------------------------------------


def _company_id(db_session):
    from app.core.seeding import DEMO_COMPANY_SLUG

    return db_session.scalars(
        select(Company).where(Company.slug == DEMO_COMPANY_SLUG)
    ).first().id


def _make_part_request(db_session, *, quantity=1):
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
        article="",
        quantity=quantity,
        status=PRS.ready_for_search,
        structured_data={"intent_confidence": 0.9},
    )
    db_session.add(pr)
    db_session.commit()
    return pr


def _search(db_session, pr):
    return PartsSearchService(db_session).search(pr, triggered_by="user")


def _company(db_session):
    return db_session.scalars(select(Company)).first()


def test_pricing_min_margin_floors_margin(db_session):
    _company(db_session).settings = {"pricing": {"margin_percent": 10}}
    db_session.commit()
    CompanyPolicyService(db_session).update(
        _company_id(db_session), pricing={"min_margin_percent": 20}
    )
    pr = _make_part_request(db_session)
    _search(db_session, pr)
    summary = PricingService(db_session).process(pr.id)
    assert summary["margin_percent"] == 20.0
    assert summary["best_unit_price"] == "7320.00"  # 6100 * 1.2


def test_pricing_rounding_to_step(db_session):
    CompanyPolicyService(db_session).update(
        _company_id(db_session), pricing={"rounding": 50}
    )
    pr = _make_part_request(db_session)
    _search(db_session, pr)
    PricingService(db_session).process(pr.id)
    offers = PartsSearchService(db_session).list_offers(pr.id)
    by_article = {o.article: o for o in offers}
    assert by_article["GDB2119"].customer_price == Decimal("7950.00")  # 7930 → 7950


def test_pricing_min_profit_raises_price(db_session):
    CompanyPolicyService(db_session).update(
        _company_id(db_session), pricing={"min_profit": 3000}
    )
    pr = _make_part_request(db_session)
    _search(db_session, pr)
    PricingService(db_session).process(pr.id)
    offers = PartsSearchService(db_session).list_offers(pr.id)
    by_article = {o.article: o for o in offers}
    # profit floor 3000 → unit = 6100 + 3000 = 9100
    assert by_article["GDB2119"].customer_price == Decimal("9100.00")


# --- Supplier policy --------------------------------------------------------


def _supplier(db_session):
    return db_session.scalars(select(Supplier)).first()


def test_supplier_policy_blocks_brand(db_session):
    CompanyPolicyService(db_session).update(
        _company_id(db_session), supplier={"blocked_brands": ["TRW"]}
    )
    pr = _make_part_request(db_session)
    run = _search(db_session, pr)
    assert run["offers_found"] == 1
    offers = PartsSearchService(db_session).list_offers(pr.id)
    assert {o.brand for o in offers} == {"BREMBO"}


def test_supplier_policy_max_lead_days(db_session):
    CompanyPolicyService(db_session).update(
        _company_id(db_session), supplier={"max_lead_days": 1}
    )
    pr = _make_part_request(db_session)
    run = _search(db_session, pr)
    assert run["offers_found"] == 1
    offers = PartsSearchService(db_session).list_offers(pr.id)
    assert {o.brand for o in offers} == {"TRW"}  # BREMBO is 2 days


def test_supplier_policy_favorite_first_with_max_variants(db_session):
    CompanyPolicyService(db_session).update(
        _company_id(db_session),
        supplier={"favorite_brands": ["BREMBO"], "max_variants": 1},
    )
    pr = _make_part_request(db_session)
    run = _search(db_session, pr)
    assert run["offers_found"] == 1
    offers = PartsSearchService(db_session).list_offers(pr.id)
    assert {o.brand for o in offers} == {"BREMBO"}


def test_supplier_policy_cheapest_wins_max_variants(db_session):
    CompanyPolicyService(db_session).update(
        _company_id(db_session), supplier={"max_variants": 1}
    )
    pr = _make_part_request(db_session)
    run = _search(db_session, pr)
    assert run["offers_found"] == 1
    offers = PartsSearchService(db_session).list_offers(pr.id)
    assert {o.article for o in offers} == {"GDB2119"}  # cheaper


def test_supplier_policy_min_rating_excludes_supplier(db_session):
    supplier = _supplier(db_session)
    supplier.settings = {"rating": 5}
    db_session.commit()
    CompanyPolicyService(db_session).update(
        _company_id(db_session), supplier={"min_rating": 8}
    )
    pr = _make_part_request(db_session)
    run = _search(db_session, pr)
    assert run["offers_found"] == 0


# --- API --------------------------------------------------------------------


def test_api_get_returns_defaults(client):
    resp = client.get("/api/v1/company-policies")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "company_id", "pricing", "supplier", "approval", "sales", "security", "defaults",
    }
    assert body["sales"]["auto_send_quote"] is False
    assert body["defaults"]["supplier"]["max_variants"] == 5


def test_api_put_partial_and_get(client, db_session):
    resp = client.put(
        "/api/v1/company-policies",
        json={"pricing": {"min_margin_percent": 15}, "sales": {"auto_send_quote": True}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pricing"]["min_margin_percent"] == 15
    assert body["sales"]["auto_send_quote"] is True

    resp = client.get("/api/v1/company-policies")
    body = resp.json()
    assert body["pricing"]["min_margin_percent"] == 15
    assert body["pricing"]["rounding"] == 0.01


# --- End-to-end: sales/approval policies drive auto-send ---------------------


def _priced_quote(client, db_session):
    pr = _make_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    resp = client.post(f"/api/v1/part_requests/{pr.id}/price")
    assert resp.status_code == 200
    return resp.json()["quote_id"]


def test_sales_policy_auto_send_quote(client, db_session):
    # 3.8.3a AND logic: auto_send_quote on + amount ceiling configured.
    client.put(
        "/api/v1/company-policies",
        json={
            "sales": {"auto_send_quote": True},
            "approval": {"auto_approve_quote_amount": 10000},
        },
    )
    quote_id = _priced_quote(client, db_session)
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message_sent"] is True
    assert body["status"] == "sent"
    assert body["approval_id"] is None


def test_sales_policy_auto_send_quote_needs_both_flags(client, db_session):
    """auto_send_quote alone (no amount ceiling) must NOT auto-send."""
    client.put(
        "/api/v1/company-policies",
        json={"sales": {"auto_send_quote": True}},
    )
    quote_id = _priced_quote(client, db_session)
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["message_sent"] is False
    assert resp.json()["status"] == "pending"


def test_approval_policy_amount_threshold_below_sends(client, db_session):
    client.put(
        "/api/v1/company-policies",
        json={
            "sales": {"auto_send_quote": True},
            "approval": {"auto_approve_quote_amount": 10000},
        },
    )
    quote_id = _priced_quote(client, db_session)  # best total 7930 ≤ 10000
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["message_sent"] is True
    assert resp.json()["status"] == "sent"


def test_approval_policy_amount_threshold_above_requires_approval(client, db_session):
    client.put(
        "/api/v1/company-policies",
        json={
            "sales": {"auto_send_quote": True},
            "approval": {"auto_approve_quote_amount": 5000},
        },
    )
    quote_id = _priced_quote(client, db_session)  # best total 7930 > 5000
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json={})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message_sent"] is False
    assert body["status"] == "pending"
    assert body["approval_id"] is not None
