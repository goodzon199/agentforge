from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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


def _priced(client, db_session) -> tuple[str, str, str]:
    pr = _make_ready_part_request(db_session)
    client.post(f"/api/v1/part_requests/{pr.id}/search")
    resp = client.post(f"/api/v1/part_requests/{pr.id}/price")
    assert resp.status_code == 200
    data = resp.json()
    return str(pr.id), data["quote_id"], str(pr.conversation_id)


def _send(client, quote_id, message=None):
    payload = {"message": message} if message is not None else {}
    resp = client.post(f"/api/v1/quotes/{quote_id}/send", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["approval_id"]


def _sales_messages(client, conversation_id):
    detail = client.get(f"/api/v1/conversations/{conversation_id}").json()
    return [
        m
        for m in detail["messages"]
        if m["sender_type"] == "agent"
        and (m.get("structured_data") or {}).get("kind") == "sales"
    ]


def test_approve_sends_message_and_marks_quote_sent(client, db_session):
    part_request_id, quote_id, conversation_id = _priced(client, db_session)
    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    approval_id = _send(client, quote_id, draft["ai_draft"])

    resp = client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["message_sent"] is True

    sales = _sales_messages(client, conversation_id)
    assert len(sales) == 1
    assert sales[0]["content"] == draft["ai_draft"]
    assert sales[0]["structured_data"]["quote_id"] == quote_id

    after = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    assert after["status"] == "sent"
    assert after["final_message"] == draft["ai_draft"]


def test_approve_sends_manager_edited_text(client, db_session):
    part_request_id, quote_id, conversation_id = _priced(client, db_session)
    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    edited = (
        "Здравствуйте! Рекомендую TRW GDB2119 за 7 930 ₽, "
        "срок 1 день, в наличии 3 шт."
    )

    prepared = client.post(
        f"/api/v1/quotes/{quote_id}/prepare", json={"message": edited}
    )
    assert prepared.status_code == 200
    assert prepared.json()["manager_edited"] == edited
    assert prepared.json()["ai_draft"] == draft["ai_draft"]

    approval_id = _send(client, quote_id)
    approve = client.post(f"/api/v1/approvals/{approval_id}/approve")
    assert approve.status_code == 200

    sales = _sales_messages(client, conversation_id)
    assert len(sales) == 1
    assert sales[0]["content"] == edited

    # Feedback distinguishes an edited approval from an untouched one.
    from app.models import AgentFeedback

    feedback = db_session.scalars(select(AgentFeedback)).all()
    assert any(
        f.feedback_type.value == "approved_edited" and f.final_output == edited
        for f in feedback
    )


def test_approve_untouched_records_approved_unchanged_feedback(client, db_session):
    part_request_id, quote_id, conversation_id = _priced(client, db_session)
    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    approval_id = _send(client, quote_id, draft["ai_draft"])
    client.post(f"/api/v1/approvals/{approval_id}/approve")

    from app.models import AgentFeedback

    feedback = db_session.scalars(select(AgentFeedback)).all()
    assert any(
        f.feedback_type.value == "approved_unchanged"
        and f.original_output == draft["ai_draft"]
        and f.final_output == draft["ai_draft"]
        for f in feedback
    )


def test_reject_does_not_send_and_quote_returns_to_draft(client, db_session):
    part_request_id, quote_id, conversation_id = _priced(client, db_session)
    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    approval_id = _send(client, quote_id, draft["ai_draft"])

    resp = client.post(
        f"/api/v1/approvals/{approval_id}/reject",
        json={"rejection_reason": "Слишком дорого"},
    )
    assert resp.status_code == 200
    assert resp.json()["message_sent"] is False
    assert resp.json()["already_rejected"] is False

    assert _sales_messages(client, conversation_id) == []
    after = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    assert after["status"] == "draft"

    approval = client.get(f"/api/v1/approvals/{approval_id}").json()
    assert approval["status"] == "rejected"
    assert approval["rejection_reason"] == "Слишком дорого"

    # Rejecting again is idempotent.
    again = client.post(
        f"/api/v1/approvals/{approval_id}/reject", json={}
    )
    assert again.status_code == 200
    assert again.json()["already_rejected"] is True


def test_approve_guard_recheck_blocks_bad_payload(client, db_session):
    from app.models import ApprovalRequest, Quote
    from app.models.enums import ApprovalRiskLevel, ApprovalStatus

    part_request_id, quote_id, conversation_id = _priced(client, db_session)
    quote = db_session.get(Quote, uuid.UUID(quote_id))

    approval = ApprovalRequest(
        company_id=quote.company_id,
        conversation_id=quote.conversation_id,
        quote_id=quote.id,
        action_type="send_customer_message",
        status=ApprovalStatus.pending,
        payload={"quote_id": quote_id, "message": "TRW GDB2119 — 6 100 ₽"},
        risk_level=ApprovalRiskLevel.medium,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(approval)
    db_session.commit()

    resp = client.post(f"/api/v1/approvals/{approval.id}/approve")
    assert resp.status_code == 422
    assert resp.json()["detail"]["guard"]["passed"] is False
    assert _sales_messages(client, conversation_id) == []


def test_expired_approval_cannot_be_approved(client, db_session):
    from app.models import ApprovalRequest, Quote
    from app.models.enums import ApprovalRiskLevel, ApprovalStatus

    part_request_id, quote_id, conversation_id = _priced(client, db_session)
    quote = db_session.get(Quote, uuid.UUID(quote_id))

    approval = ApprovalRequest(
        company_id=quote.company_id,
        conversation_id=quote.conversation_id,
        quote_id=quote.id,
        action_type="send_customer_message",
        status=ApprovalStatus.pending,
        payload={"quote_id": quote_id, "message": "текст"},
        risk_level=ApprovalRiskLevel.medium,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(approval)
    db_session.commit()

    resp = client.post(f"/api/v1/approvals/{approval.id}/approve")
    assert resp.status_code == 409
    assert _sales_messages(client, conversation_id) == []


def test_approval_other_company_forbidden(client, db_session):
    from app.models import ApprovalRequest, Company
    from app.models.enums import ApprovalRiskLevel, ApprovalStatus

    other = Company(name="Другая компания", slug="other-company")
    db_session.add(other)
    db_session.commit()

    approval = ApprovalRequest(
        company_id=other.id,
        action_type="send_customer_message",
        status=ApprovalStatus.pending,
        payload={},
        risk_level=ApprovalRiskLevel.medium,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(approval)
    db_session.commit()

    assert client.post(f"/api/v1/approvals/{approval.id}/approve").status_code == 403
    assert client.post(f"/api/v1/approvals/{approval.id}/reject", json={}).status_code == 403
    assert client.get(f"/api/v1/approvals/{approval.id}").status_code == 403

    # The scoped list never leaks the other company's request.
    ids = [a["id"] for a in client.get("/api/v1/approvals").json()]
    assert str(approval.id) not in ids


def test_approval_404(client, db_session):
    resp = client.post(f"/api/v1/approvals/{uuid.uuid4()}/approve")
    assert resp.status_code == 404


def test_actions_list_and_detail(client, db_session):
    part_request_id, quote_id, conversation_id = _priced(client, db_session)
    draft = client.get(f"/api/v1/quotes/{quote_id}/sales-draft").json()
    approval_id = _send(client, quote_id, draft["ai_draft"])
    client.post(f"/api/v1/approvals/{approval_id}/approve")

    actions = client.get("/api/v1/actions").json()
    sends = [a for a in actions if a["action_type"] == "send_customer_message"]
    assert len(sends) == 1
    action = sends[0]
    assert action["status"] == "executed"
    assert action["risk_level"] == "MEDIUM"
    assert action["requires_approval"] is True
    assert action["executed_at"] is not None

    detail = client.get(f"/api/v1/actions/{action['id']}").json()
    assert detail["id"] == action["id"]
