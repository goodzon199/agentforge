from __future__ import annotations

from sqlalchemy import select

from app.models import (
    ApprovalRequest,
    Company,
    ConversationMessage,
    PartRequest,
    Quote,
    SupplierSearchAttempt,
    SupplierSearchRun,
    User,
)
from app.models.enums import (
    ApprovalRiskLevel,
    ApprovalStatus,
    ConversationMode,
    QuoteStatus,
    SupplierAttemptStatus,
    SupplierSearchStatus,
)
from app.models.enums import (
    PartRequestStatus as PRS,
)
from app.models.shadow_comparison import (
    SHADOW_STATUS_COMPLETED,
    SHADOW_STATUS_PENDING,
    ShadowComparison,
)
from app.services.manager_dashboard_service import ManagerDashboardService
from app.services.shadow_service import ShadowService


def _company_id(db_session):
    return db_session.scalars(select(Company).where(Company.slug == "demo")).first().id


def _make_request(db_session, *, company_id, status=PRS.ready_for_search, part="Тормозные колодки", article="", vehicle_text=""):
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
    pr = PartRequest(
        company_id=company_id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        source_message_id=message.id,
        part_name=part,
        article=article,
        quantity=1,
        status=status,
        missing_fields=[],
        structured_data={"intent_confidence": 0.9},
    )
    db_session.add(pr)
    db_session.commit()
    return pr, conversation, message


def _add_run(db_session, pr, *, status=SupplierSearchStatus.completed, offers_found=3):
    from datetime import UTC, datetime

    run = SupplierSearchRun(
        part_request_id=pr.id,
        status=status,
        offers_found=offers_found,
        completed_at=datetime.now(UTC) if status == SupplierSearchStatus.completed else None,
    )
    db_session.add(run)
    db_session.flush()
    return run


def _add_failed_attempt(db_session, run):
    from app.models import Supplier

    supplier = db_session.scalars(select(Supplier)).first()
    attempt = SupplierSearchAttempt(
        search_run_id=run.id,
        supplier_id=supplier.id,
        status=SupplierAttemptStatus.failed,
        error="timeout",
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


# --- Shadow Mode creation hook ---------------------------------------------


def test_intake_opens_shadow_comparison(db_session, make_conversation):
    """A new part request (via IntakeService.process) opens a pending shadow
    comparison for a company running shadow mode."""
    from app.schemas.intake import IntakeResult, PartInput, VehicleInput
    from app.services.intake_service import IntakeService

    company_id = _company_id(db_session)
    company = db_session.get(Company, company_id)
    company.shadow_mode = True

    _, _, conversation, message = make_conversation("Нужны колодки на BMW X5 2019")
    result = IntakeResult(
        intent="part_search",
        vehicle=VehicleInput(brand="BMW", model="X5", year=2019),
        part=PartInput(name="тормозные колодки"),
        missing_fields=[],
        ready_for_search=True,
        clarification_question=None,
        confidence=0.8,
    )
    agent_id = db_session.scalars(
        select(User).where(User.is_superuser.is_(True))
    ).first().id
    IntakeService(db_session).process(conversation, message, result, agent_id=agent_id)
    db_session.commit()

    comparisons = db_session.scalars(
        select(ShadowComparison).where(ShadowComparison.company_id == company_id)
    ).all()
    assert len(comparisons) == 1
    comparison = comparisons[0]
    assert comparison.status == SHADOW_STATUS_PENDING
    assert comparison.ai_vehicle == "BMW X5 2019"
    assert comparison.ai_part == "тормозные колодки"


def test_shadow_hook_skipped_when_disabled(db_session, make_conversation):
    from app.schemas.intake import IntakeResult, PartInput, VehicleInput
    from app.services.intake_service import IntakeService

    company_id = _company_id(db_session)
    company = db_session.get(Company, company_id)
    company.shadow_mode = False

    _, _, conversation, message = make_conversation("Нужны колодки на BMW X5")
    result = IntakeResult(
        intent="part_search",
        vehicle=VehicleInput(brand="BMW", model="X5"),
        part=PartInput(name="тормозные колодки"),
        missing_fields=[],
        ready_for_search=True,
        clarification_question=None,
        confidence=0.9,
    )
    agent_id = db_session.scalars(
        select(User).where(User.is_superuser.is_(True))
    ).first().id
    IntakeService(db_session).process(conversation, message, result, agent_id=agent_id)
    db_session.commit()

    count = db_session.scalar(
        select(__import__("sqlalchemy").func.count())
        .select_from(ShadowComparison)
        .where(ShadowComparison.company_id == company_id)
    )
    assert count == 0


def test_shadow_limit_halts_new_comparisons(db_session, make_conversation):
    from app.core.config import settings
    from app.services.shadow_service import ShadowService

    company_id = _company_id(db_session)
    pr, conversation, message = _make_request(db_session, company_id=company_id)
    service = ShadowService(db_session)
    comparison = service.ensure_for_part_request(pr)
    db_session.commit()
    assert comparison is not None

    saved = settings.shadow_mode_limit
    settings.shadow_mode_limit = 1
    try:
        pr2, _, _ = _make_request(db_session, company_id=company_id)
        second = service.ensure_for_part_request(pr2)
        assert second is None
    finally:
        settings.shadow_mode_limit = saved


def test_shadow_duplicate_is_idempotent(db_session, make_conversation):
    company_id = _company_id(db_session)
    pr, _, _ = _make_request(db_session, company_id=company_id)
    service = ShadowService(db_session)
    first = service.ensure_for_part_request(pr)
    second = service.ensure_for_part_request(pr)
    db_session.commit()
    assert first is not None and first.id == second.id
    count = db_session.scalar(
        select(__import__("sqlalchemy").func.count())
        .select_from(ShadowComparison)
        .where(ShadowComparison.part_request_id == pr.id)
    )
    assert count == 1


# --- Manager submission & comparison ---------------------------------------


def test_submit_manager_completes_and_matches(db_session, make_conversation):
    company_id = _company_id(db_session)
    pr, conversation, _ = _make_request(
        db_session, company_id=company_id, part="Тормозные колодки", article="0345",
    )
    service = ShadowService(db_session)
    comparison = service.ensure_for_part_request(pr)
    comparison.ai_vehicle = "BMW X5 2019"
    db_session.commit()

    comparison = service.submit_manager(
        pr,
        vehicle="BMW X5 2019",
        part="Тормозные Колодки",
        article="0345",
        offer_ids=["a"],
        price=2500,
        reply="Готово, подобрал колодки!",
    )
    service.add_manager_reply(conversation, comparison, user_id=None)
    db_session.commit()

    assert comparison.status == SHADOW_STATUS_COMPLETED
    assert comparison.part_match is True
    assert comparison.oem_match is True
    assert comparison.vehicle_match is True
    assert comparison.evaluated_at is not None
    assert comparison.time_seconds is not None and comparison.time_seconds >= 0

    # The manager's reply is stored as a manager message tagged for shadow.
    messages = db_session.scalars(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation.id
        )
    ).all()
    manager_msgs = [m for m in messages if m.sender_type == "manager"]
    assert len(manager_msgs) == 1
    assert manager_msgs[0].structured_data.get("kind") == "shadow"
    assert manager_msgs[0].structured_data.get("comparison_id") == str(comparison.id)


def test_submit_manager_price_delta_and_overlap(db_session, make_conversation):
    company_id = _company_id(db_session)
    pr, _, _ = _make_request(db_session, company_id=company_id)
    service = ShadowService(db_session)
    comparison = service.ensure_for_part_request(pr)
    db_session.commit()

    # AI side has already produced a quote (best selection snapshot).

    quote = Quote(
        company_id=company_id,
        part_request_id=pr.id,
        conversation_id=pr.conversation_id,
        status=QuoteStatus.draft,
        items=[{"offer_id": "a"}, {"offer_id": "b"}],
        quote_total=2000,
        final_message="",
    )
    db_session.add(quote)
    db_session.commit()

    comparison = service.submit_manager(
        pr, offer_ids=["a", "c"], price=2500, reply="ok"
    )
    db_session.commit()
    assert comparison.price_delta == 500
    assert comparison.offer_overlap == 1


def test_submit_manager_returns_error_when_shadow_disabled(db_session, make_conversation):
    import pytest

    company_id = _company_id(db_session)
    company = db_session.get(Company, company_id)
    company.shadow_mode = False
    pr, _, _ = _make_request(db_session, company_id=company_id)
    with pytest.raises(ValueError):
        ShadowService(db_session).submit_manager(pr, reply="x")


# --- Dashboard --------------------------------------------------------------

def test_dashboard_attention_and_counts(db_session, make_conversation):
    company_id = _company_id(db_session)

    # 1) client waiting reply: open conversation, human takeover, last msg = customer.
    from app.services.conversation_service import ConversationService

    cs = ConversationService(db_session)
    customer = cs.create_customer(company_id=company_id, name="Пётр")
    db_session.add(customer)
    db_session.flush()
    wait_conv = cs.create_conversation(
        company_id=company_id, customer_id=customer.id, channel="web"
    )
    wait_conv.mode = ConversationMode.human_active
    db_session.add(wait_conv)
    db_session.flush()
    cs.add_message(wait_conv, content="А когда ответите?", sender_type="customer")
    db_session.commit()

    pr, conversation, _ = _make_request(db_session, company_id=company_id)
    # Agent has already replied in this conversation -> not "client waiting".
    ConversationService(db_session).add_message(
        conversation, content="Уточните, пожалуйста, VIN", sender_type="agent"
    )
    # sqlite now() has second precision: force a monotonic order so the
    # "latest message" subquery is deterministic.
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    for conv, delta in ((wait_conv, 0), (conversation, 2)):
        messages = conv.messages
        for i, message in enumerate(messages):
            message.created_at = base + timedelta(seconds=delta + i)
    pr.structured_data = {"intent_confidence": 0.55}
    db_session.commit()

    run = _add_run(db_session, pr, status=SupplierSearchStatus.completed, offers_found=3)
    _add_failed_attempt(db_session, run)

    # 2) a sent quote -> not selection-ready anymore + counts "sent" today.
    quote = Quote(
        company_id=company_id,
        part_request_id=pr.id,
        conversation_id=conversation.id,
        status=QuoteStatus.sent,
        items=[{"offer_id": "1"}],
        quote_total=2500,
        final_message="Добрый день!",
        sent_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
    )
    db_session.add(quote)
    db_session.commit()

    data = ManagerDashboardService(db_session).dashboard(company_id)

    attention = data["attention"]
    assert attention["client_waiting_reply"] == 1
    assert attention["ai_unsure"] == 1
    assert attention["supplier_error"] == 1

    today = data["today"]
    assert today["requests"] >= 1
    assert today["selections"] >= 1
    assert today["quotes"] >= 1
    assert today["sent"] >= 1

    queue = data["queue"]
    assert any(item["type"] == "needs_reply" for item in queue)


def test_dashboard_approval_pending_in_queue(db_session, make_conversation):
    company_id = _company_id(db_session)
    pr, conversation, _ = _make_request(db_session, company_id=company_id)
    quote = Quote(
        company_id=company_id,
        part_request_id=pr.id,
        conversation_id=conversation.id,
        status=QuoteStatus.pending_approval,
        items=[],
    )
    db_session.add(quote)
    db_session.flush()
    approval = ApprovalRequest(
        company_id=company_id,
        conversation_id=conversation.id,
        quote_id=quote.id,
        action_type="send_customer_message",
        status=ApprovalStatus.pending,
        risk_level=ApprovalRiskLevel.medium,
    )
    db_session.add(approval)
    db_session.commit()

    data = ManagerDashboardService(db_session).dashboard(company_id)
    assert data["attention"]["approval_pending"] == 1
    items = [i for i in data["queue"] if i["type"] == "approval_pending"]
    assert len(items) == 1
    assert items[0]["quote_id"] == str(quote.id)
    assert items[0]["approval_id"] == str(approval.id)


def test_dashboard_selection_ready_in_queue(db_session, make_conversation):
    company_id = _company_id(db_session)
    pr, conversation, _ = _make_request(db_session, company_id=company_id)
    _add_run(db_session, pr, status=SupplierSearchStatus.completed, offers_found=4)

    data = ManagerDashboardService(db_session).dashboard(company_id)
    items = [i for i in data["queue"] if i["type"] == "selection_ready"]
    assert len(items) == 1
    assert items[0]["part_request_id"] == str(pr.id)
    assert items[0]["action"] == "open"
    assert "4" in items[0]["title"]


def test_dashboard_shadow_stats_embedded(db_session, make_conversation):
    company_id = _company_id(db_session)
    pr, _, _ = _make_request(db_session, company_id=company_id)
    service = ShadowService(db_session)
    service.ensure_for_part_request(pr)
    service.submit_manager(pr, part="Тормозные колодки", reply="ок")
    db_session.commit()

    data = ManagerDashboardService(db_session).dashboard(company_id)
    assert data["shadow"]["total"] == 1
    assert data["shadow"]["completed"] == 1
    assert data["shadow"]["part_match_pct"] == 100.0
