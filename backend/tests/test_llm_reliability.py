from __future__ import annotations

import httpx
from sqlalchemy import func, select

from app.core.config import settings
from app.llm.client import LLMClient, TaskLLMProxy
from app.llm.errors import LLMErrorKind, classify_exception
from app.llm.types import LLMMessage, LLMResponse
from app.models import Agent, Company, LLMUsage
from app.orchestrator.orchestrator import orchestrator
from app.services.task_service import TaskService


class _ScriptedProvider:
    """Provider that plays back a script of outcomes, one per call."""

    def __init__(self, script: list[str]) -> None:
        self.script = list(script)
        self.calls = 0

    def chat(self, *, messages, model, temperature, max_tokens):
        if not self.script:
            raise AssertionError("script exhausted")
        outcome = self.script.pop(0)
        self.calls += 1
        if outcome == "ok":
            return LLMResponse(
                content="ответ",
                model=model,
                raw={"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
            )
        if outcome == "empty":
            return LLMResponse(content="", model=model)
        if outcome == "timeout":
            raise httpx.ReadTimeout("read timed out")
        if outcome == "connect":
            raise httpx.ConnectError("connection refused")
        if outcome == "error":
            raise RuntimeError("boom")
        raise AssertionError(f"unknown outcome {outcome!r}")


class _FakeLLMClient:
    """LLMClient-shaped object the orchestrator can be pointed at."""

    available = True
    model = "qwen2.5:3b"

    def __init__(self) -> None:
        self.last_attempts: list[dict] = []
        self.last_error_kind = None
        self.stats = {"calls": 0, "failures": 0}

    def chat(self, messages, *, model=None, temperature=None, max_tokens=None):
        self.last_attempts = [{"status": "ok", "duration_ms": 1}]
        self.last_error_kind = None
        return LLMResponse(
            content='{"needs_agent": null, "reason": "ok", "answer": "ок"}',
            model=self.model,
            raw={"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        )

    def embed(self, text, *, model=None):
        return None


def _apply_retry_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_max_attempts", 2)
    monkeypatch.setattr(settings, "llm_retry_initial_delay", 0.01)
    monkeypatch.setattr(settings, "llm_retry_max_delay", 0.01)


def _client(script: list[str]) -> LLMClient:
    client = LLMClient()
    client._provider = _ScriptedProvider(script)
    return client


def _new_agent(db_session) -> Agent:
    company = db_session.scalars(select(Company)).first()
    agent = Agent(company_id=company.id, name="Test", role="test", slug="test-llm-agent")
    db_session.add(agent)
    db_session.flush()
    return agent


def _new_task(db_session):
    company = db_session.scalars(select(Company)).first()
    task = TaskService(db_session).create(
        company_id=company.id, title="Задача", objective="test"
    )
    db_session.flush()
    return task


def _usage_count(db_session, agent_id) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(LLMUsage)
            .where(LLMUsage.agent_id == agent_id)
        )
        or 0
    )


# --- total_llm_calls: source of truth is LLMUsage ---------------------------


def test_successful_llm_call_counts_one(db_session, monkeypatch):
    _apply_retry_settings(monkeypatch)
    proxy = TaskLLMProxy(_client(["ok"]))
    agent = _new_agent(db_session)
    task = _new_task(db_session)

    resp = proxy.chat([LLMMessage(role="user", content="привет")])
    assert resp is not None
    assert len(proxy._usage) == 1
    assert proxy._usage[0]["status"] == "ok"
    assert proxy._usage[0]["total_tokens"] == 15

    assert proxy.flush(db_session, task_id=task.id, company_id=agent.company_id, agent_id=agent.id) == 1
    orchestrator._update_statistics(db_session, agent, success=True)
    db_session.commit()

    assert agent.total_llm_calls == 1
    assert _usage_count(db_session, agent.id) == 1


def test_failed_attempt_counted_separately(db_session, monkeypatch):
    _apply_retry_settings(monkeypatch)
    proxy = TaskLLMProxy(_client(["error"]))  # non-transient → no retry
    agent = _new_agent(db_session)
    task = _new_task(db_session)

    resp = proxy.chat([LLMMessage(role="user", content="привет")])
    assert resp is None
    assert len(proxy._usage) == 1
    assert proxy._usage[0]["status"] == "error"
    assert proxy._usage[0]["total_tokens"] == 0

    assert proxy.flush(db_session, task_id=task.id, company_id=agent.company_id, agent_id=agent.id) == 1
    orchestrator._update_statistics(db_session, agent, success=True)
    db_session.commit()

    assert agent.total_llm_calls == 1
    assert _usage_count(db_session, agent.id) == 1


def test_two_calls_in_one_task_count_two(db_session, monkeypatch):
    _apply_retry_settings(monkeypatch)
    proxy = TaskLLMProxy(_client(["ok", "ok"]))
    agent = _new_agent(db_session)
    task = _new_task(db_session)

    proxy.chat([LLMMessage(role="user", content="а")])
    proxy.chat([LLMMessage(role="user", content="б")])
    assert len(proxy._usage) == 2

    assert proxy.flush(db_session, task_id=task.id, company_id=agent.company_id, agent_id=agent.id) == 2
    orchestrator._update_statistics(db_session, agent, success=True)
    db_session.commit()

    assert agent.total_llm_calls == 2
    assert _usage_count(db_session, agent.id) == 2


def test_retry_attempt_is_not_lost(db_session, monkeypatch):
    _apply_retry_settings(monkeypatch)
    proxy = TaskLLMProxy(_client(["timeout", "ok"]))
    agent = _new_agent(db_session)
    task = _new_task(db_session)

    resp = proxy.chat([LLMMessage(role="user", content="привет")])
    assert resp is not None
    assert [u["status"] for u in proxy._usage] == ["timeout", "ok"]
    assert proxy._usage[0]["total_tokens"] == 0
    assert proxy._usage[1]["total_tokens"] == 15

    assert proxy.flush(db_session, task_id=task.id, company_id=agent.company_id, agent_id=agent.id) == 2
    orchestrator._update_statistics(db_session, agent, success=True)
    db_session.commit()

    assert agent.total_llm_calls == 2
    assert _usage_count(db_session, agent.id) == 2


def test_reprocessing_task_does_not_inflate_statistics(db_session, monkeypatch):
    _apply_retry_settings(monkeypatch)
    agent = _new_agent(db_session)
    task = _new_task(db_session)

    first = TaskLLMProxy(_client(["ok"]))
    first.chat([LLMMessage(role="user", content="а")])
    assert first.flush(db_session, task_id=task.id, company_id=agent.company_id, agent_id=agent.id) == 1
    orchestrator._update_statistics(db_session, agent, success=True)
    db_session.commit()
    assert agent.total_llm_calls == 1

    # Re-processing spawns a fresh proxy (as the orchestrator would) that makes
    # a real call, but flush is idempotent per task → no duplicate rows.
    again = TaskLLMProxy(_client(["ok"]))
    again.chat([LLMMessage(role="user", content="б")])
    assert len(again._usage) == 1
    assert again.flush(db_session, task_id=task.id, company_id=agent.company_id, agent_id=agent.id) == 0
    orchestrator._update_statistics(db_session, agent, success=True)
    db_session.commit()

    assert agent.total_llm_calls == 1
    assert _usage_count(db_session, agent.id) == 1


# --- timeout / normalized outcomes ------------------------------------------


def test_client_retries_only_transient(monkeypatch):
    _apply_retry_settings(monkeypatch)

    client = _client(["error"])  # business error → not retried
    resp = client.chat([LLMMessage(role="user", content="х")])
    assert resp is None
    assert len(client.last_attempts) == 1
    assert client.last_attempts[0]["status"] == "error"

    client = _client(["timeout", "ok"])  # transient → retried, both attempts visible
    resp = client.chat([LLMMessage(role="user", content="х")])
    assert resp is not None
    assert [a["status"] for a in client.last_attempts] == ["timeout", "ok"]

    client = _client(["connect", "ok"])  # unavailable → retried too
    resp = client.chat([LLMMessage(role="user", content="х")])
    assert resp is not None
    assert [a["status"] for a in client.last_attempts] == ["unavailable", "ok"]


def test_invalid_empty_response_is_not_retried(monkeypatch):
    _apply_retry_settings(monkeypatch)
    client = _client(["empty"])
    resp = client.chat([LLMMessage(role="user", content="х")])
    assert resp is None
    assert len(client.last_attempts) == 1
    assert client.last_attempts[0]["status"] == "invalid_response"


def test_client_without_provider_reports_unavailable():
    client = LLMClient()  # no OPENAI_API_KEY in test env
    resp = client.chat([LLMMessage(role="user", content="х")])
    assert resp is None
    assert client.last_attempts[0]["status"] == "unavailable"


def test_classify_exception_maps_kinds():
    assert classify_exception(httpx.ReadTimeout("t")) is LLMErrorKind.TIMEOUT
    assert classify_exception(httpx.ConnectTimeout("t")) is LLMErrorKind.TIMEOUT
    assert classify_exception(httpx.ConnectError("c")) is LLMErrorKind.UNAVAILABLE
    assert classify_exception(RuntimeError("boom")) is LLMErrorKind.ERROR


# --- orchestrator wiring -----------------------------------------------------


def test_orchestrator_derives_total_llm_calls_from_usage(db_session, monkeypatch):
    fake = _FakeLLMClient()
    saved = orchestrator.llm
    orchestrator.llm = fake
    try:
        company = db_session.scalars(select(Company)).first()
        task = TaskService(db_session).create(
            company_id=company.id,
            title="Отчёт",
            objective="Подготовь отчёт по продажам",
        )
        db_session.commit()

        orchestrator.process(db_session, task)
        db_session.flush()
        system = db_session.scalars(select(Agent).where(Agent.slug == "system-agent")).first()
        assert task.status.value == "completed"
        assert system.total_llm_calls == 1
        assert _usage_count(db_session, system.id) == 1

        # Re-processing the same task must not inflate the counter.
        orchestrator.process(db_session, task)
        db_session.flush()
        db_session.refresh(system)
        assert system.total_llm_calls == 1
        assert _usage_count(db_session, system.id) == 1
    finally:
        orchestrator.llm = saved
