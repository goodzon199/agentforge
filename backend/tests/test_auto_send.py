from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import (
    AgentAction,
    AgentFeedback,
    Company,
    ConversationMessage,
    PartRequest,
    Quote,
    Supplier,
    SupplierOffer,
    User,
)
from app.models.enums import (
    AgentFeedbackType,
    QuoteStatus,
)
from app.models.enums import (
    PartRequestStatus as PRS,
)
from app.services.auto_send_service import AutoSendService
from app.services.manager_dashboard_service import ManagerDashboardService
from app.services.sales_service import SalesService


def _company_id(db_session):
    return db_session.scalars(select(Company).where(Company.slug == "demo")).first().id


def _make_request(
    db_session, *, company_id, confidence=0.9, fitment=None, vehicle=False, missing_fields=None, intent="part_search", article="0345"
):
    from app.services.conversation_service import ConversationService

    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=company_id, name="Иван Петров")
    db_session.add(customer)
    db_session.flush()
    conversation = cs.create_conversation(
        company_id=company_id, customer_id=customer.id, channel="web"
    )
    db_session.add(conversation)
    db_session.flush()
    message, _ = cs.add_message(conversation, content="Нужны колодки", sender_type="customer")
    db_session.add(message)
    db_session.flush()
    structured = {"intent_confidence": confidence}
    if fitment is not None:
        structured["fitment_confidence"] = fitment
    vehicle_id = None
    if vehicle:
        from app.models import Vehicle

        v = Vehicle(
            company_id=company_id,
            customer_id=customer.id,
            brand="BMW",
            model="X5",
            vin="WBAKX4100B1234567",
        )
        db_session.add(v)
        db_session.flush()
        vehicle_id = v.id
    pr = PartRequest(
        company_id=company_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        source_message_id=message.id,
        part_name="Тормозные колодки",
        article=article,
        quantity=1,
        status=PRS.ready_for_search,
        missing_fields=missing_fields or [],
        intent=intent,
        vehicle_id=vehicle_id,
        structured_data=structured,
    )
    db_session.add(pr)
    db_session.commit()
    return pr, conversation


def _quote(db_session, *, company_id, part_request, guard_status="pass", items=None, total="2000"):
    offer = SupplierOffer(
        part_request_id=part_request.id,
        search_run_id=_run_id(db_session, part_request),
        supplier_id=db_session.scalars(select(Supplier)).first().id,
        brand="BREMBO",
        article="0345",
        part_name="Тормозные колодки",
        purchase_price=1000,
        customer_price=1500,
        total_price=1500,
    )
    db_session.add(offer)
    db_session.flush()
    if items is None:
        items = [{"offer_id": str(offer.id), "brand": "BREMBO", "article": "0345", "total_price": "2000"}]
    quote = Quote(
        company_id=company_id,
        part_request_id=part_request.id,
        conversation_id=part_request.conversation_id,
        status=QuoteStatus.draft,
        guard_status=guard_status,
        items=items,
        quote_total=total,
        ai_draft="Здравствуйте! Подобрал колодки.",
    )
    db_session.add(quote)
    db_session.commit()
    return quote, offer


def _run_id(db_session, part_request):
    from app.models import SupplierSearchRun
    from app.models.enums import SupplierSearchStatus

    run = SupplierSearchRun(
        part_request_id=part_request.id,
        status=SupplierSearchStatus.completed,
        offers_found=1,
    )
    db_session.add(run)
    db_session.flush()
    return run.id


def _set_policy(db_session, company_id, sales=None, approval=None):
    from app.services.company_policy_service import CompanyPolicyService

    if sales and sales.get("auto_send_quote") is True and not approval:
        # 3.8.3a: auto-send also requires an approved amount ceiling.
        approval = {"auto_approve_quote_amount": 10000}
    CompanyPolicyService(db_session).update(company_id, sales=sales, approval=approval)


# --- AutoSendService decision ------------------------------------------------


def test_decision_allows_when_all_safe(db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is True
    assert decision["blocks"] == []
    assert decision["checks"] == {
        "policy": True,
        "guard": True,
        "intent": True,
        "fitment": True,
        "supplier": True,
        "standard": True,
    }


def test_decision_blocks_low_confidence(db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id, confidence=0.4)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("Уверенность" in b for b in decision["blocks"])


def test_decision_blocks_out_of_range_confidence(db_session):
    """intent_confidence outside 0..1 must never pass (e.g. a legacy 9.5)."""
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id, confidence=9.5)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("вне шкалы" in b for b in decision["blocks"])


def test_decision_blocks_vehicle_fitment_without_engine(db_session):
    """VIN-dependent pick without proven fitment is never auto-sent.

    Sprint 4.0: the Fitment Engine is the single source of truth — an article
    not in the catalog (unknown vehicle fitment) stays uncertain even if a
    legacy ``fitment_confidence`` is present in structured_data.
    """
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(
        db_session, company_id=company_id, vehicle=True, fitment=0.95, article="NO-SUCH-ARTICLE"
    )
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("fitment" in b.lower() for b in decision["blocks"])


def test_decision_blocks_vehicle_unknown_article(db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id, vehicle=True, article="NO-SUCH-ARTICLE")
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("fitment" in b.lower() for b in decision["blocks"])


def test_decision_allows_vehicle_with_proven_fitment(db_session):
    """Catalog fitment + cross reference + accumulated order evidence cross
    the 0.9 fitment floor and allow Controlled Auto for a VIN-dependent pick."""
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id, vehicle=True, article="GDB3410")
    from app.models import PartFitmentEvidence, Vehicle

    vehicle = db_session.scalars(select(Vehicle).where(Vehicle.company_id == company_id)).first()
    db_session.add(
        PartFitmentEvidence(
            company_id=company_id,
            part_request_id=pr.id,
            vehicle_id=vehicle.id,
            article="GDB3410",
            source="order_history",
            confidence=1.0,
            detail={"order_number": "ORD-0001"},
        )
    )
    db_session.commit()
    quote, offer = _quote(db_session, company_id=company_id, part_request=pr)
    offer.article = "GDB3410"
    quote.items = [{"offer_id": str(offer.id), "brand": "TRW", "article": "GDB3410", "total_price": "2000"}]
    db_session.commit()

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is True
    assert decision["blocks"] == []


def test_decision_blocks_guard_blocked(db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr, guard_status="block")

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("QuoteGuard" in b for b in decision["blocks"])


def test_decision_blocks_low_supplier_rating(db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    supplier = db_session.scalars(select(Supplier)).first()
    supplier.settings = {"rating": 0.2}
    db_session.commit()
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("Надёжность" in b for b in decision["blocks"])


def test_decision_blocks_out_of_range_supplier_rating(db_session):
    """A legacy 10-point rating (e.g. 9.5) must NEVER pass a 0.8 threshold."""
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    supplier = db_session.scalars(select(Supplier)).first()
    supplier.settings = {"rating": 9.5}
    db_session.commit()
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("шкалы" in b for b in decision["blocks"])


def test_decision_blocks_missing_supplier_rating(db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    supplier = db_session.scalars(select(Supplier)).first()
    supplier.settings = {}
    db_session.commit()
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False


def test_decision_blocks_nonstandard_request(db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id, missing_fields=["vehicle"], intent="general_question")
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("Нестандартный" in b or "Интент" in b for b in decision["blocks"])


def test_decision_blocks_when_policy_off(db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": False})
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("auto_send_quote" in b for b in decision["blocks"])


def test_decision_blocks_amount_above_ceiling(db_session):
    """AND logic: auto_send_quote on but total above the ceiling -> manager."""
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr, total="50000")

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("превышает" in b for b in decision["blocks"])


def test_decision_blocks_amount_without_ceiling(db_session):
    """auto_send_quote on but no amount ceiling configured -> never auto."""
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True}, approval={"auto_approve_quote_amount": None})
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    decision = AutoSendService(db_session).decision(quote)
    assert decision["auto"] is False
    assert any("порог" in b for b in decision["blocks"])


# --- Controlled Auto end-to-end through SalesService ------------------------


def test_request_send_auto_when_safe(client, db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    result = SalesService(db_session).request_send(quote, None, _admin(db_session))
    db_session.commit()

    assert result["status"] == "sent"
    assert result["message_sent"] is True
    assert result.get("auto_sent") is True
    assert quote.status == QuoteStatus.sent
    # The send action carries the auto decision.
    action = db_session.scalars(
        select(AgentAction).where(AgentAction.action_type == "send_customer_message")
    ).first()
    assert (action.result_data or {}).get("auto_send", {}).get("auto") is True


def test_request_send_auto_records_audit_snapshot(client, db_session):
    """3.8.3a: the full decision snapshot is stored on the quote."""
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    SalesService(db_session).request_send(quote, None, _admin(db_session))
    db_session.commit()

    assert quote.auto_sent is True
    assert quote.auto_sent_at is not None
    snap = quote.auto_send_decision
    assert snap is not None
    assert snap["policy"] is True
    assert snap["guard"] is True
    assert snap["intent"] is True
    assert snap["fitment"] is True
    assert snap["supplier"] is True
    assert snap["standard"] is True
    assert snap["thresholds"]["auto_send_min_confidence"] == 0.7
    assert snap["thresholds"]["auto_approve_quote_amount"] == 10000
    assert snap["quote_version"] >= 1
    # The idempotency key is version-scoped.
    action = db_session.scalars(
        select(AgentAction).where(AgentAction.action_type == "send_customer_message")
    ).first()
    assert action.idempotency_key == f"auto_send_quote:{quote.id}:{snap['quote_version']}"


def test_request_send_double_auto_send_is_idempotent(client, db_session):
    """3.8.3a: a retry after an auto-send must not send twice."""
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, conversation = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    service = SalesService(db_session)
    first = service.request_send(quote, None, _admin(db_session))
    db_session.commit()
    assert first["auto_sent"] is True

    second = service.request_send(quote, None, _admin(db_session))
    db_session.commit()
    assert second["already_executed"] is True
    assert second["message_sent"] is True

    messages = db_session.scalars(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation.id
        )
    ).all()
    assert sum(1 for m in messages if m.sender_type == "agent") == 1


def test_request_send_goes_to_approval_when_unsafe(client, db_session):
    company_id = _company_id(db_session)
    _set_policy(db_session, company_id, sales={"auto_send_quote": True})
    pr, _ = _make_request(db_session, company_id=company_id, confidence=0.4)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    result = SalesService(db_session).request_send(quote, None, _admin(db_session))
    db_session.commit()

    assert result["status"] == "pending"
    assert result["message_sent"] is False
    assert result.get("auto_sent") in (None, False)
    assert result["approval_id"] is not None
    assert quote.status == QuoteStatus.pending_approval


def test_request_send_approve_now_one_click(client, db_session):
    """Assist Mode: a single manager click both creates and approves."""
    company_id = _company_id(db_session)
    pr, conversation = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    result = SalesService(db_session).request_send(
        quote, "Подобрал колодки, жду решения", _admin(db_session), approve_now=True
    )
    db_session.commit()

    assert result["status"] == "approved"
    assert result["message_sent"] is True
    # The customer received the message.
    messages = db_session.scalars(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation.id
        )
    ).all()
    assert any(m.sender_type == "agent" for m in messages)
    # Feedback recorded for manager_edit_rate (a manager-typed message = edited).
    feedback = db_session.scalars(
        select(AgentFeedback).where(AgentFeedback.company_id == company_id)
    ).all()
    assert any(fb.feedback_type == AgentFeedbackType.approved_edited for fb in feedback)


def _admin(db_session):
    return db_session.scalars(select(User).where(User.is_superuser.is_(True))).first()


# --- Manager edit rate (Assist Mode metric) ---------------------------------


def test_dashboard_assist_manager_edit_rate(db_session):
    company_id = _company_id(db_session)
    for fb_type, n in ((AgentFeedbackType.approved_unchanged, 3), (AgentFeedbackType.approved_edited, 1)):
        for _ in range(n):
            db_session.add(
                AgentFeedback(
                    company_id=company_id,
                    feedback_type=fb_type,
                    original_output="a",
                    final_output="b",
                )
            )
    db_session.commit()

    assist = ManagerDashboardService(db_session).assist(company_id)
    assert assist["sends_total"] == 4
    assert assist["sends_unchanged"] == 3
    assert assist["sends_edited"] == 1
    assert assist["manager_edit_rate"] == 75.0


def test_dashboard_includes_assist_block(db_session):
    company_id = _company_id(db_session)
    data = ManagerDashboardService(db_session).dashboard(company_id)
    assert "assist" in data
    assert data["assist"]["sends_total"] == 0
    assert data["assist"]["manager_edit_rate"] is None


def test_assist_unchanged_edit_rates_through_approval_flow(db_session):
    """Manager approves an AI draft unchanged -> approved_unchanged counted."""
    from app.services.sales_service import SalesService

    company_id = _company_id(db_session)
    pr, conversation = _make_request(db_session, company_id=company_id)
    quote, _ = _quote(db_session, company_id=company_id, part_request=pr)

    service = SalesService(db_session)
    result = service.request_send(quote, None, _admin(db_session))
    assert result["status"] == "pending"
    service.approve(uuid.UUID(result["approval_id"]), _admin(db_session))
    db_session.commit()

    feedback = db_session.scalars(
        select(AgentFeedback).where(
            AgentFeedback.company_id == company_id,
            AgentFeedback.feedback_type == AgentFeedbackType.approved_unchanged,
        )
    ).all()
    assert len(feedback) == 1
    assist = ManagerDashboardService(db_session).assist(company_id)
    assert assist["manager_edit_rate"] == 100.0
