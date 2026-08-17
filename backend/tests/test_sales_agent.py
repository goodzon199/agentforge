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


def _priced(client, db_session) -> tuple[str, str]:
    """Search + price a fresh part request; returns (part_request_id, quote_id)."""
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    resp = client.post(f"/api/v1/part_requests/{pr.id}/price")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "priced"
    return str(pr.id), data["quote_id"]


def _actions(client):
    return client.get("/api/v1/actions").json()


def test_pricing_hands_off_to_sales(client, db_session):
    part_request_id, quote_id = _priced(client, db_session)

    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    assert draft["status"] == "draft"
    assert draft["ai_draft"]
    assert draft["guard_status"] == "pass"
    assert draft["currency"] == "RUB"
    assert draft["quote_total"] is not None
    assert len(draft["items"]) == 2

    # Draft only quotes facts from the quote, never purchase prices.
    message = draft["ai_draft"]
    for forbidden in ("6800", "6100", "margin", "закуп", "наценк"):
        assert forbidden.lower() not in message.lower()


def test_sales_agent_audit_trail(client, db_session):
    part_request_id, quote_id = _priced(client, db_session)

    actions = _actions(client)
    prepare = [a for a in actions if a["action_type"] == "prepare_sales_draft"]
    assert len(prepare) == 1
    action = prepare[0]
    assert action["risk_level"].lower() == "low"
    assert action["requires_approval"] is False
    assert action["status"] == "executed"
    assert action["target_type"] == "quote"
    assert action["target_id"] == quote_id
    assert action["agent_id"] is not None


def test_sales_draft_404(client, db_session):
    resp = client.get(f"/api/v1/quotes/{uuid.uuid4()}/sales-draft")
    assert resp.status_code == 404


def test_send_creates_approval_and_blocks_duplicate(client, db_session):
    part_request_id, quote_id = _priced(client, db_session)
    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()

    send = client.post(
        f"/api/v1/quotes/{quote_id}/send", json={"message": draft["ai_draft"]}
    )
    assert send.status_code == 200
    result = send.json()
    assert result["status"] == "pending"
    assert result["message_sent"] is False
    approval_id = result["approval_id"]

    approvals = client.get("/api/v1/approvals").json()
    assert any(a["id"] == approval_id for a in approvals)

    # Same send again returns the same pending approval — no new request.
    again = client.post(
        f"/api/v1/quotes/{quote_id}/send", json={"message": draft["ai_draft"]}
    )
    assert again.status_code == 200
    assert again.json()["approval_id"] == approval_id
    assert again.json()["status"] == "pending"

    # Only one pending approval exists for this quote.
    mine = [
        a
        for a in client.get("/api/v1/approvals").json()
        if a["quote_id"] == quote_id and a["status"] == "pending"
    ]
    assert len(mine) == 1


def test_send_blocks_quote_guard_violation(client, db_session):
    part_request_id, quote_id = _priced(client, db_session)

    bad = "TRW GDB2119 — 6 100 ₽"
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json={"message": bad})
    assert resp.status_code == 422
    assert resp.json()["detail"]["guard"]["passed"] is False

    # The blocked attempt is audited as a failed action.
    actions = _actions(client)
    failed = [
        a
        for a in actions
        if a["action_type"] == "send_customer_message" and a["status"] == "failed"
    ]
    assert len(failed) == 1


def test_send_retry_after_guard_block_is_not_500(client, db_session):
    part_request_id, quote_id = _priced(client, db_session)
    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()

    bad = "TRW GDB2119 — 6 100 ₽"
    blocked = client.post(f"/api/v1/quotes/{quote_id}/send", json={"message": bad})
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["guard"]["passed"] is False

    # A corrected retry must NOT crash on the UNIQUE idempotency key that the
    # guard-block audit used to occupy (live 500 regression, post-3.8.3a).
    good = client.post(
        f"/api/v1/quotes/{quote_id}/send", json={"message": draft["ai_draft"]}
    )
    assert good.status_code == 200
    result = good.json()
    assert result["status"] == "pending"
    assert result["message_sent"] is False
    assert result["approval_id"]

    # The block is still audited once (guard_blocked key), the retry got its
    # own send action — no idempotency collision.
    actions = _actions(client)
    failed = [
        a
        for a in actions
        if a["action_type"] == "send_customer_message" and a["status"] == "failed"
    ]
    assert len(failed) == 1
    blocked_keys = [
        a["idempotency_key"]
        for a in actions
        if a["action_type"] == "send_customer_message" and a["status"] == "failed"
    ]
    assert all(k and k.endswith(":guard_blocked") for k in blocked_keys)


def test_send_uses_stored_draft_when_message_omitted(client, db_session):
    part_request_id, quote_id = _priced(client, db_session)
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    assert resp.json()["message_sent"] is False
