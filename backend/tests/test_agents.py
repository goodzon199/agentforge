from __future__ import annotations

from sqlalchemy import select

from app.agents.system import SystemAgent
from app.core.seeding import SYSTEM_AGENT_SLUG
from app.llm.client import LLMClient
from app.memory.service import MemoryService
from app.models import Agent
from app.tools.registry import ToolRegistry


def _make_agent(db_session) -> SystemAgent:
    record = db_session.scalars(
        select(Agent).where(Agent.slug == SYSTEM_AGENT_SLUG)
    ).first()
    return SystemAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=ToolRegistry(),
        llm=LLMClient(),
    )


def test_system_agent_routes_brake_pads_to_search(db_session):
    agent = _make_agent(db_session)
    output = agent.execute("Найди тормозные колодки", {})
    assert output.handoff_agent == "SearchAgent"
    assert "SearchAgent" in output.response
    assert output.routing_decision["engine"] == "rules"


def test_system_agent_routes_email(db_session):
    agent = _make_agent(db_session)
    output = agent.execute("Отправь письмо клиенту", {})
    assert output.handoff_agent == "EmailAgent"


def test_system_agent_generic_task_no_handoff(db_session):
    agent = _make_agent(db_session)
    output = agent.execute("Подготовь отчёт по продажам", {})
    assert output.handoff_agent is None


def test_system_agent_writes_short_memory(db_session):
    from sqlalchemy import select

    from app.models import ShortMemory

    agent = _make_agent(db_session)
    output = agent.execute("Найди тормозные колодки", {})
    agent.remember(output.response, kind="task_result")
    db_session.commit()
    entries = db_session.scalars(select(ShortMemory)).all()
    assert len(entries) >= 1


def test_email_agent_sends_through_stubbed_tool(db_session):
    from sqlalchemy import select

    from app.agents.email import EmailAgent
    from app.tools.base import ToolResult

    record = db_session.scalars(
        select(Agent).where(Agent.slug == "email-agent")
    ).first()

    class _FakeTools:
        def run(self, name, **kwargs):
            assert name == "email"
            assert kwargs["to"] == "client@example.com"
            assert kwargs["subject"] == "Тест"
            assert "текст письма" in kwargs["body"]
            return ToolResult(
                ok=True,
                data={
                    "to": "client@example.com",
                    "subject": "Тест",
                    "from": "agentforge@agentos.local",
                    "transport": "mailhog:1025",
                },
            )

    agent = EmailAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=_FakeTools(),
        llm=LLMClient(),
    )
    output = agent.execute(
        "Напиши письмо",
        {"to": "client@example.com", "subject": "Тест", "body": "текст письма"},
    )
    assert output.data["action"] == "email_sent"
    assert output.data["to"] == "client@example.com"
    assert "Письмо отправлено" in output.response


def test_email_agent_falls_back_to_default_recipient(db_session):
    from sqlalchemy import select

    from app.agents.email import EmailAgent
    from app.core.config import settings
    from app.tools.base import ToolResult

    record = db_session.scalars(
        select(Agent).where(Agent.slug == "email-agent")
    ).first()

    class _FakeTools:
        def run(self, name, **kwargs):
            return ToolResult(
                ok=True,
                data={
                    "to": settings.email_default_to,
                    "subject": kwargs["subject"],
                    "from": settings.smtp_from,
                    "transport": "mailhog:1025",
                },
            )

    agent = EmailAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=_FakeTools(),
        llm=LLMClient(),
    )
    output = agent.execute("Отправь письмо о встрече", {})
    assert output.data["to"] == settings.email_default_to
    assert "встрече" in output.data["subject"]


def test_search_agent_finds_knowledge(db_session):
    from sqlalchemy import select

    from app.agents.search import SearchAgent

    record = db_session.scalars(
        select(Agent).where(Agent.slug == "search-agent")
    ).first()
    agent = SearchAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=ToolRegistry(),
        llm=LLMClient(),
    )
    output = agent.execute("Найди тормозные колодки", {})
    assert output.data["action"] == "search_done"
    assert output.data["found"] is True
    assert any("TRW" in r["title"] for r in output.data["results"])
    assert "колодки" in output.data["results"][0]["title"].lower()


def test_search_agent_returns_not_found(db_session):
    from sqlalchemy import select

    from app.agents.search import SearchAgent

    record = db_session.scalars(
        select(Agent).where(Agent.slug == "search-agent")
    ).first()
    agent = SearchAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=ToolRegistry(),
        llm=LLMClient(),
    )
    output = agent.execute("Найди глушитель для Volvo FH", {})
    assert output.data["found"] is False
    assert "ничего не найдено" in output.response


def test_search_query_extraction():
    from app.agents.search import extract_query

    assert extract_query("Найди тормозные колодки", {}) == "тормозные колодки"
    assert extract_query("Поищи масло Castrol", {}) == "масло Castrol"
    assert extract_query("тормозные колодки", {}) == "тормозные колодки"
    assert extract_query("x", {"query": "масляный фильтр"}) == "масляный фильтр"


def test_search_agent_uses_vector_search_when_available(db_session, monkeypatch):
    import hashlib
    import re

    from sqlalchemy import select

    from app.agents.search import SearchAgent
    from app.core.config import settings
    from app.memory.service import entry_text

    class _FakeLLM:
        available = True

        def embed(self, text, model=None):
            vector = [0.0] * 32
            for token in re.findall(r"\w+", text.lower()):
                digest = int(hashlib.md5(token.encode()).hexdigest()[:4], 16) % 32
                vector[digest] += 1.0
            return vector

    monkeypatch.setattr("app.memory.service.llm_client", _FakeLLM())
    monkeypatch.setattr(settings, "embedding_model", "test-embed")

    record = db_session.scalars(
        select(Agent).where(Agent.slug == "search-agent")
    ).first()

    agent = SearchAgent(
        record=record,
        memory=MemoryService(db_session),
        tools=ToolRegistry(),
        llm=LLMClient(),
    )
    output = agent.execute("Найди тормозные колодки", {})
    assert output.data["mode"] == "vector"
    assert output.data["found"] is True
    assert output.data["results"][0]["score"] > 0.3
    assert "TRW" in output.data["results"][0]["title"]


def test_vector_search_ranks_relevant_entry_first(db_session, monkeypatch):
    import hashlib
    import re

    from sqlalchemy import select

    from app.core.config import settings
    from app.memory.service import MemoryService, cosine_similarity

    class _FakeLLM:
        available = True

        def embed(self, text, model=None):
            vector = [0.0] * 32
            for token in re.findall(r"\w+", text.lower()):
                digest = int(hashlib.md5(token.encode()).hexdigest()[:4], 16) % 32
                vector[digest] += 1.0
            return vector

    monkeypatch.setattr("app.memory.service.llm_client", _FakeLLM())
    monkeypatch.setattr(settings, "embedding_model", "test-embed")

    memory = MemoryService(db_session)
    company = db_session.scalars(select(Agent)).first().company
    memory.embed_missing(company.id)

    results = memory.vector_search(company.id, "масло моторное", top_k=3)
    assert len(results) == 3
    top_title = results[0][0].title
    assert "Масло" in top_title
    assert results[0][1] > results[1][1]


def test_cosine_similarity_basic():
    from app.memory.service import cosine_similarity

    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_entry_text_joins_title_content_tags(db_session):
    from app.memory.service import entry_text

    from app.models import KnowledgeEntry

    entry = db_session.scalars(select(KnowledgeEntry)).first()
    text = entry_text(entry)
    assert entry.title in text
    assert "Тэги:" in text
