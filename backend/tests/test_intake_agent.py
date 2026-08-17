from __future__ import annotations

import json

from sqlalchemy import select

from app.llm.types import LLMResponse


def _intake_agent(db_session, llm=None):
    from app.agents.intake_agent import IntakeAgent
    from app.llm.client import LLMClient
    from app.memory.service import MemoryService
    from app.models import Agent
    from app.tools.registry import ToolRegistry

    record = db_session.scalars(
        select(Agent).where(Agent.slug == "intake-agent")
    ).first()
    return IntakeAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=ToolRegistry(),
        llm=llm or LLMClient(),
        db=db_session,
    )


def _run(agent, conversation, message):
    return agent.execute(
        "process_customer_message",
        {"conversation_id": str(conversation.id), "message_id": str(message.id)},
    )


def test_intake_creates_part_request_and_asks_for_vin(
    db_session, make_conversation
):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Нужны передние колодки на BMW X5 2019")
    agent = _intake_agent(db_session)
    output = _run(agent, conversation, message)

    assert output.data["action"] == "part_request_created"
    assert output.data["intent"] == "part_search"
    assert output.data["ready_for_search"] is False
    assert output.data["missing_fields"] == ["vin"]
    assert "VIN" in output.response

    part_request = db_session.scalars(select(PartRequest)).first()
    assert part_request is not None
    assert part_request.part_name == "передние тормозные колодки"
    assert part_request.status.value == "collecting_data"
    assert part_request.vehicle.brand == "BMW"
    assert part_request.vehicle.model == "X5"
    assert part_request.vehicle.year == 2019

    # The agent reply is stored in the conversation.
    replies = [
        m for m in conversation.messages if m.sender_type == "agent"
    ]
    assert len(replies) == 1
    assert "VIN" in replies[0].content


def test_intake_uses_valid_llm_result(db_session, make_conversation):
    from app.llm.types import LLMMessage

    payload = json.dumps(
        {
            "intent": "part_search",
            "vehicle": {"vin": "WBAKS410900H12345", "brand": "BMW", "model": "X5", "year": 2019},
            "part": {"name": "передние тормозные колодки", "article": None, "quantity": 1},
            "missing_fields": [],
            "ready_for_search": True,
            "clarification_question": None,
            "confidence": 0.9,
        }
    )

    class _FakeLLM:
        available = True

        def __init__(self):
            self.last_messages = None

        def chat(self, *, messages: list[LLMMessage], **kwargs):
            self.last_messages = messages
            return LLMResponse(content=payload, model="fake")

    fake = _FakeLLM()
    agent = _intake_agent(db_session, llm=fake)
    _, _, conversation, message = make_conversation("Нужны колодки BMW")
    output = _run(agent, conversation, message)

    assert output.data["ready_for_search"] is True
    assert output.data["intent"] == "part_search"
    assert fake.last_messages is not None
    assert any(m.role == "system" for m in fake.last_messages)


def test_intake_bare_vin_not_missed_by_llm(db_session, make_conversation):
    from app.llm.types import LLMMessage
    from app.models import PartRequest

    payload = json.dumps(
        {
            "intent": "part_search",
            "vehicle": None,
            "part": None,
            "missing_fields": ["vin"],
            "ready_for_search": False,
            "clarification_question": None,
            "confidence": 0.9,
        }
    )

    class _FakeLLM:
        available = True

        def chat(self, *, messages: list[LLMMessage], **kwargs):
            return LLMResponse(content=payload, model="fake")

    agent = _intake_agent(db_session, llm=_FakeLLM())
    _, _, conversation, message = make_conversation("JTNB11HK803030803")
    output = _run(agent, conversation, message)

    assert output.data["intent"] == "part_search"
    part_request = db_session.scalars(select(PartRequest)).first()
    assert part_request is not None
    assert part_request.vehicle is not None
    assert part_request.vehicle.vin == "JTNB11HK803030803"
    assert "VIN" not in output.response  # does not ask for the VIN again
    assert "детал" in output.response.lower()


def test_intake_injects_vin_llm_missed(db_session, make_conversation):
    from app.llm.types import LLMMessage
    from app.models import PartRequest

    payload = json.dumps(
        {
            "intent": "part_search",
            "vehicle": {"brand": "BMW", "model": "X5", "year": 2019},
            "part": {"name": "передние тормозные колодки", "quantity": 1},
            "missing_fields": ["vin"],
            "ready_for_search": False,
            "clarification_question": None,
            "confidence": 0.9,
        }
    )

    class _FakeLLM:
        available = True

        def chat(self, *, messages: list[LLMMessage], **kwargs):
            return LLMResponse(content=payload, model="fake")

    agent = _intake_agent(db_session, llm=_FakeLLM())
    _, _, conversation, message = make_conversation(
        "Колодки на BMW X5 2019 VIN WBAKS410900H12345"
    )
    output = _run(agent, conversation, message)

    part_request = db_session.scalars(select(PartRequest)).first()
    assert part_request.vehicle.brand == "BMW"
    assert part_request.vehicle.model == "X5"
    assert part_request.vehicle.vin == "WBAKS410900H12345"
    assert output.data["ready_for_search"] is True


def test_intake_falls_back_to_rules_on_invalid_llm(db_session, make_conversation):
    from app.llm.types import LLMMessage

    class _BrokenLLM:
        available = True

        def chat(self, *, messages: list[LLMMessage], **kwargs):
            return LLMResponse(content="извините, я не понял", model="fake")

    agent = _intake_agent(db_session, llm=_BrokenLLM())
    _, _, conversation, message = make_conversation("Нужны передние колодки на BMW X5 2019")
    output = _run(agent, conversation, message)

    # The agent still returns a valid contract via the rules engine.
    assert output.data["action"] == "part_request_created"
    assert output.data["intent"] == "part_search"
    assert output.data["missing_fields"] == ["vin"]


def test_intake_low_confidence_ignored_in_favour_of_rules(db_session, make_conversation):
    from app.llm.types import LLMMessage

    payload = json.dumps(
        {
            "intent": "general_question",
            "vehicle": None,
            "part": None,
            "missing_fields": [],
            "ready_for_search": False,
            "clarification_question": "что?",
            "confidence": 0.2,
        }
    )

    class _FakeLLM:
        available = True

        def chat(self, *, messages: list[LLMMessage], **kwargs):
            return LLMResponse(content=payload, model="fake")

    agent = _intake_agent(db_session, llm=_FakeLLM())
    _, _, conversation, message = make_conversation("Нужны колодки на BMW X5 2019")
    output = _run(agent, conversation, message)

    # Low-confidence LLM output is discarded in favour of the rules result.
    assert output.data["intent"] == "part_search"
    assert output.data["ready_for_search"] is False


def test_intake_order_status_creates_no_part_request(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Где мой заказ?")
    agent = _intake_agent(db_session)
    output = _run(agent, conversation, message)

    assert output.data["action"] == "replied"
    assert output.data["intent"] == "order_status"
    assert db_session.scalars(select(PartRequest)).first() is None


def test_intake_complaint_creates_no_part_request(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Хочу вернуть деталь")
    agent = _intake_agent(db_session)
    output = _run(agent, conversation, message)

    assert output.data["intent"] == "complaint"
    assert db_session.scalars(select(PartRequest)).first() is None


def test_intake_general_question_creates_no_part_request(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Вы работаете сегодня?")
    agent = _intake_agent(db_session)
    output = _run(agent, conversation, message)

    assert output.data["intent"] == "general_question"
    assert db_session.scalars(select(PartRequest)).first() is None


def test_intake_missing_ids_returns_error(db_session, make_conversation):
    agent = _intake_agent(db_session)
    output = agent.execute("process_customer_message", {})
    assert output.data["action"] == "error"
    assert output.data["reason"] == "missing_ids"


def test_intake_parses_oil_filter_article(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Ищу масляный фильтр 11428507683")
    agent = _intake_agent(db_session)
    output = _run(agent, conversation, message)

    assert output.data["intent"] == "part_search"
    part_request = db_session.scalars(select(PartRequest)).first()
    assert part_request.part_name == "масляный фильтр"
    assert part_request.article == "11428507683"
    assert part_request.quantity == 1


def test_intake_parses_quantity_and_vehicle(db_session, make_conversation):
    from app.models import PartRequest

    _, _, conversation, message = make_conversation("Нужно 2 передних рычага на Kia Rio 2017")
    agent = _intake_agent(db_session)
    _run(agent, conversation, message)

    part_request = db_session.scalars(select(PartRequest)).first()
    assert part_request.quantity == 2
    assert part_request.part_name == "передний рычаг"
    assert part_request.vehicle.brand == "Kia"
    assert part_request.vehicle.model == "Rio"
    assert part_request.vehicle.year == 2017
