from __future__ import annotations

from sqlalchemy import select

from app.schemas.intake import IntakeResult, PartInput, VehicleInput
from app.services.intake_service import IntakeService


def _result(
    intent="part_search",
    vehicle=None,
    part=None,
    missing=None,
    ready=False,
    clarification=None,
):
    return IntakeResult(
        intent=intent,
        vehicle=vehicle,
        part=part,
        missing_fields=missing or [],
        ready_for_search=ready,
        clarification_question=clarification,
        confidence=0.8,
    )


def _process(db_session, conversation, message, result, agent_id=None):
    from app.models import Agent

    if agent_id is None:
        agent_id = db_session.scalars(
            select(Agent).where(Agent.slug == "intake-agent")
        ).first().id
    outcome = IntakeService(db_session).process(conversation, message, result, agent_id=agent_id)
    db_session.commit()
    return outcome


def _veh(vin="", brand="", model="", year=None, engine=""):
    return VehicleInput(vin=vin, brand=brand, model=model, year=year, engine=engine)


def _part(name, article="", quantity=1):
    return PartInput(name=name, article=article or None, quantity=quantity)


def test_creates_part_request_collecting_data(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Нужны колодки на BMW X5 2019")
    outcome = _process(
        db_session,
        conversation,
        message,
        _result(vehicle=_veh(brand="BMW", model="X5", year=2019), part=_part("тормозные колодки")),
    )

    assert outcome.action == "part_request_created"
    assert outcome.ready_for_search is False
    assert outcome.missing_fields == ["vin"]
    assert "VIN" in outcome.reply

    part_request = db_session.scalars(select(PartRequest)).first()
    assert part_request.status.value == "collecting_data"
    assert part_request.source_message_id == message.id


def test_intake_records_pilot_event_log_milestones(db_session, make_conversation):
    from app.models import AuditEvent

    _, _, conversation, message = make_conversation("Нужны колодки на BMW X5")
    _process(
        db_session, conversation, message,
        _result(vehicle=_veh(brand="BMW", model="X5"), part=_part("тормозные колодки")),
    )

    events = db_session.scalars(
        select(AuditEvent).where(AuditEvent.company_id == conversation.company_id)
    ).all()
    actions = [e.action for e in events]
    assert "customer_message_received" in actions
    assert "part_request_created" in actions

    received = next(e for e in events if e.action == "customer_message_received")
    assert received.entity_type == "conversation_message"
    assert received.entity_id == str(message.id)
    assert received.detail["conversation_id"] == str(conversation.id)

    created = next(e for e in events if e.action == "part_request_created")
    assert created.entity_type == "part_request"


def test_intake_continuation_logs_part_request_updated(db_session, make_conversation):
    from app.models import AuditEvent

    _, _, conversation, m1 = make_conversation("Нужен радиатор на Camry")
    _process(
        db_session, conversation, m1,
        _result(vehicle=_veh(brand="Toyota", model="Camry"), part=_part("радиатор")),
    )

    m2 = _message(db_session, conversation, "2018 год, двигатель 2.5")
    _process(
        db_session, conversation, m2,
        _result(vehicle=_veh(year=2018, engine="2.5"), part=None),
    )

    actions = [
        e.action
        for e in db_session.scalars(
            select(AuditEvent).where(AuditEvent.action.in_(["part_request_created", "part_request_updated"]))
        ).all()
    ]
    assert "part_request_created" in actions
    assert "part_request_updated" in actions


def test_continuation_updates_single_part_request(db_session, make_conversation):
    from app.models import PartRequest, Task

    # Message 1: request a radiator for a Camry.
    _, _, conversation, m1 = make_conversation("Нужен радиатор на Camry")
    outcome1 = _process(
        db_session, conversation, m1,
        _result(vehicle=_veh(brand="Toyota", model="Camry"), part=_part("радиатор")),
    )
    assert outcome1.action == "part_request_created"

    # Message 2: continuation with year + engine.
    m2 = _message(db_session, conversation, "2018 год, двигатель 2.5")
    outcome2 = _process(
        db_session, conversation, m2,
        _result(vehicle=_veh(year=2018, engine="2.5"), part=None),
    )
    assert outcome2.action == "part_request_updated"

    # Message 3: VIN closes the request.
    m3 = _message(db_session, conversation, "VIN JTNB11HK803030803")
    outcome3 = _process(
        db_session, conversation, m3,
        _result(vehicle=_veh(vin="JTNB11HK803030803"), part=None),
    )

    part_requests = db_session.scalars(select(PartRequest)).all()
    assert len(part_requests) == 1  # one request, not three
    pr = part_requests[0]
    assert pr.vehicle.brand == "Toyota"
    assert pr.vehicle.model == "Camry"
    assert pr.vehicle.year == 2018
    assert pr.vehicle.engine == "2.5"
    assert pr.vehicle.vin == "JTNB11HK803030803"
    assert pr.part_name == "радиатор"
    assert pr.status.value == "ready_for_search"
    assert outcome3.ready_for_search is True
    assert outcome3.search_task_id is not None

    search_task = db_session.get(Task, outcome3.search_task_id)
    assert search_task is not None
    assert search_task.objective == "search_parts"
    assert search_task.input_data["part_request_id"] == str(pr.id)
    assert search_task.input_data["query"] == "радиатор"


def test_reprocess_is_idempotent(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Нужны колодки на BMW X5")
    result = _result(vehicle=_veh(brand="BMW", model="X5"), part=_part("тормозные колодки"))
    first = _process(db_session, conversation, message, result)
    assert first.action == "part_request_created"

    second = _process(db_session, conversation, message, result)
    assert second.action == "already_processed"

    assert len(db_session.scalars(select(PartRequest)).all()) == 1


def test_ready_creates_search_parts_task(db_session, make_conversation):
    from app.models import Task

    _, _, conversation, message = make_conversation("Колодки BMW X5 VIN WBAKS410900H12345")
    outcome = _process(
        db_session, conversation, message,
        _result(vehicle=_veh(brand="BMW", model="X5", vin="WBAKS410900H12345"),
                part=_part("тормозные колодки")),
    )
    assert outcome.ready_for_search is True
    assert outcome.search_task_id is not None
    task = db_session.get(Task, outcome.search_task_id)
    assert task is not None
    assert task.objective == "search_parts"


def test_vehicle_reused_by_vin(db_session, make_conversation):
    from app.models import Vehicle

    _, _, conversation, m1 = make_conversation("Колодки на BMW X5 VIN WBAKS410900H12345")
    _process(
        db_session, conversation, m1,
        _result(vehicle=_veh(brand="BMW", model="X5", vin="WBAKS410900H12345"),
                part=_part("тормозные колодки")),
    )

    m2 = _message(db_session, conversation, "Передние диски BMW X5 VIN WBAKS410900H12345")
    _process(
        db_session, conversation, m2,
        _result(vehicle=_veh(brand="BMW", model="X5", vin="WBAKS410900H12345"),
                part=_part("тормозной диск")),
    )

    vehicles = db_session.scalars(select(Vehicle)).all()
    assert len(vehicles) == 1
    assert vehicles[0].vin == "WBAKS410900H12345"


def test_missing_part_asks_clarification(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Что-нибудь на BMW?")
    outcome = _process(
        db_session, conversation, message,
        _result(vehicle=_veh(brand="BMW"), part=None),
    )
    assert outcome.ready_for_search is False
    assert "детал" in outcome.reply.lower()
    assert db_session.scalars(select(PartRequest)).first().status.value == "collecting_data"


def test_order_status_creates_no_part_request(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Где мой заказ?")
    outcome = _process(db_session, conversation, message, _result(intent="order_status"))
    assert outcome.action == "replied"
    assert outcome.intent == "order_status"
    assert db_session.scalars(select(PartRequest)).first() is None


def test_part_search_placeholder_clarification_falls_back(db_session, make_conversation):
    from app.models import ConversationMessage

    _, _, conversation, message = make_conversation("Найди масло ngn 5w30 profi")
    outcome = _process(
        db_session, conversation, message,
        _result(vehicle=_veh(), part=_part("моторное масло"), clarification="...|null"),
    )
    assert outcome.ready_for_search is False
    assert outcome.reply != "...|null"
    assert "автомобил" in outcome.reply.lower()

    agent_msg = db_session.scalars(
        select(ConversationMessage).where(ConversationMessage.sender_type == "agent")
    ).first()
    assert agent_msg is not None
    assert agent_msg.content == outcome.reply
    assert agent_msg.content != "...|null"


def test_part_search_null_string_clarification_falls_back(db_session, make_conversation):
    _, _, conversation, message = make_conversation("Найди масло ngn 5w30 profi")
    outcome = _process(
        db_session, conversation, message,
        _result(vehicle=_veh(), part=_part("моторное масло"), clarification="null"),
    )
    assert outcome.reply != "null"
    assert "автомобил" in outcome.reply.lower()


def test_other_intent_placeholder_clarification_falls_back(db_session, make_conversation):
    from app.models import ConversationMessage

    _, _, conversation, message = make_conversation("Сколько стоит?")
    outcome = _process(
        db_session, conversation, message,
        _result(intent="general_question", clarification="...|null"),
    )
    assert outcome.action == "replied"
    assert outcome.reply == "Передал вопрос сотруднику — отвечу в ближайшее время."

    agent_msg = db_session.scalars(
        select(ConversationMessage).where(ConversationMessage.sender_type == "agent")
    ).first()
    assert agent_msg.content == outcome.reply


def test_legit_clarification_kept(db_session, make_conversation):
    _, _, conversation, message = make_conversation("Найди масло")
    outcome = _process(
        db_session, conversation, message,
        _result(
            vehicle=_veh(), part=_part("моторное масло"),
            clarification="Укажите марку и модель авто",
        ),
    )
    assert outcome.reply == "Укажите марку и модель авто"


def test_complaint_creates_no_part_request(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Хочу вернуть деталь")
    outcome = _process(db_session, conversation, message, _result(intent="complaint"))
    assert outcome.action == "replied"
    assert outcome.intent == "complaint"
    assert db_session.scalars(select(PartRequest)).first() is None


def test_general_question_creates_no_part_request(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Вы работаете сегодня?")
    outcome = _process(db_session, conversation, message, _result(intent="general_question"))
    assert outcome.action == "replied"
    assert db_session.scalars(select(PartRequest)).first() is None


def test_continuation_year_and_engine_merge(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, m1 = make_conversation("Нужен радиатор на Camry")
    _process(
        db_session, conversation, m1,
        _result(vehicle=_veh(brand="Toyota", model="Camry"), part=_part("радиатор")),
    )

    m2 = _message(db_session, conversation, "2018 год, двигатель 2.5")
    outcome = _process(
        db_session, conversation, m2,
        _result(vehicle=_veh(year=2018, engine="2.5"), part=None),
    )

    pr = db_session.scalars(select(PartRequest)).first()
    assert pr.vehicle.year == 2018
    assert pr.vehicle.engine == "2.5"
    assert outcome.action == "part_request_updated"
    assert pr.status.value == "collecting_data"


def _message(db_session, conversation, content):
    from app.services.conversation_service import ConversationService

    message, _ = ConversationService(db_session).add_message(
        conversation, content=content, sender_type="customer"
    )
    db_session.commit()
    return message
