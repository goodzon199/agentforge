from __future__ import annotations

import time
import uuid
from datetime import UTC

import httpx
import pytest
from sqlalchemy import select

from app.models import Company, DeadTask, Task
from app.orchestrator.orchestrator import orchestrator
from app.reliability.circuit_breaker import BreakerState, CircuitBreaker, get_breaker
from app.reliability.errors import FailureKind, classify_exception
from app.reliability.retry import RetryPolicy
from app.services.task_service import TaskService

# --- RetryPolicy -------------------------------------------------------------


def test_retry_policy_only_retries_transient():
    policy = RetryPolicy(max_attempts=3)
    assert policy.should_retry(FailureKind.TIMEOUT, 1) is True
    assert policy.should_retry(FailureKind.UNAVAILABLE, 1) is True
    assert policy.should_retry(FailureKind.RATE_LIMITED, 1) is True
    assert policy.should_retry(FailureKind.AUTHENTICATION, 1) is False
    assert policy.should_retry(FailureKind.SUPPLIER_ERROR, 1) is False
    assert policy.should_retry(FailureKind.INTERNAL_ERROR, 1) is False


def test_retry_policy_stops_after_max_attempts():
    policy = RetryPolicy(max_attempts=2)
    assert policy.should_retry(FailureKind.TIMEOUT, 1) is True
    assert policy.should_retry(FailureKind.TIMEOUT, 2) is False


def test_retry_policy_backoff_grows_with_jitter():
    policy = RetryPolicy(max_attempts=5, initial_delay=1.0, factor=2.0, max_delay=8.0, jitter=False)
    assert policy.next_delay(1) == 1.0
    assert policy.next_delay(2) == 2.0
    assert policy.next_delay(3) == 4.0
    assert policy.next_delay(4) == 8.0
    assert policy.next_delay(5) == 8.0  # capped


def test_retry_policy_jitter_is_bounded(monkeypatch):
    monkeypatch.setattr("random.uniform", lambda lo, hi: lo + (hi - lo) * 0.5)
    policy = RetryPolicy(max_attempts=3, initial_delay=1.0, factor=2.0, max_delay=8.0)
    delay = policy.next_delay(2)  # base 2.0 with jitter
    assert 0 < delay < 2.0


def test_get_policy_llm_uses_dedicated_settings(monkeypatch):
    from app.core.config import settings
    from app.reliability.retry import get_policy

    monkeypatch.setattr(settings, "llm_max_attempts", 3)
    monkeypatch.setattr(settings, "retry_max_attempts", 5)
    policy = get_policy("llm")
    assert policy.max_attempts == 3
    assert get_policy("smtp").max_attempts == 5


def test_get_policy_per_service_override(monkeypatch):
    from app.core.config import settings
    from app.reliability.retry import get_policy

    monkeypatch.setattr(settings, "retry_policies", {"rossko": {"max_attempts": 4}})
    monkeypatch.setattr(settings, "retry_max_attempts", 2)
    assert get_policy("rossko").max_attempts == 4
    assert get_policy("http").max_attempts == 2


# --- CircuitBreaker ----------------------------------------------------------


def test_breaker_closed_allows_requests():
    breaker = CircuitBreaker("t", failure_threshold=3, recovery_timeout=1.0)
    assert breaker.state is BreakerState.closed
    assert breaker.allow_request() is True


def test_breaker_opens_after_threshold():
    breaker = CircuitBreaker("t", failure_threshold=3, recovery_timeout=1.0)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state is BreakerState.open
    assert breaker.allow_request() is False  # fail fast
    assert breaker.snapshot()["open_count"] == 1


def test_breaker_recovers_to_half_open_then_closes(monkeypatch):
    breaker = CircuitBreaker("t", failure_threshold=2, recovery_timeout=0.1)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is BreakerState.open

    # Wait past recovery timeout: next request is a half-open probe.
    time.sleep(0.15)
    assert breaker.allow_request() is True
    assert breaker.state is BreakerState.half_open

    breaker.record_success()
    assert breaker.state is BreakerState.closed


def test_breaker_half_open_failure_reopens(monkeypatch):
    breaker = CircuitBreaker("t", failure_threshold=2, recovery_timeout=0.1)
    breaker.record_failure()
    breaker.record_failure()
    time.sleep(0.15)
    assert breaker.allow_request() is True
    breaker.record_failure()  # probe failed -> re-open
    assert breaker.state is BreakerState.open
    assert breaker.snapshot()["open_count"] == 2


def test_breaker_success_streak_resets_failures():
    breaker = CircuitBreaker("t", failure_threshold=5, recovery_timeout=1.0)
    for _ in range(4):
        breaker.record_failure()
    for _ in range(5):
        breaker.record_success()
    breaker.record_failure()
    assert breaker.state is BreakerState.closed  # failures were reset


def test_breaker_snapshot_opened_at_is_wall_clock():
    from datetime import datetime

    breaker = CircuitBreaker("t", failure_threshold=1, recovery_timeout=1.0)
    breaker.record_failure()
    snap = breaker.snapshot()
    assert snap["opened_at"] is not None
    # monotonic() would give an epoch near boot (1970) — wall clock is "now".
    opened = datetime.fromisoformat(snap["opened_at"])
    now = datetime.now(UTC)
    assert abs((now - opened).total_seconds()) < 30


def test_breaker_registry_returns_same_instance(monkeypatch):
    from app.reliability.circuit_breaker import breaker_registry

    monkeypatch.setattr(
        "app.reliability.circuit_breaker.breaker_registry._breakers", {}
    )
    a = get_breaker("ollama")
    b = get_breaker("ollama")
    assert a is b
    assert "ollama" in breaker_registry.names()


# --- Distributed breaker (Redis, sprint 3.5.1) --------------------------------


def _redis_breaker(name, **kwargs):
    """Redis-backed breaker with a unique key; always reset at the end."""
    from app.reliability.circuit_breaker import RedisCircuitBreaker

    breaker = RedisCircuitBreaker(name, **kwargs)
    breaker.reset()
    return breaker


def test_redis_breaker_transitions_atomically():

    name = f"test-rd-{uuid.uuid4().hex[:8]}"
    b = _redis_breaker(name, failure_threshold=3, recovery_timeout=1.0)

    assert b.allow_request() is True
    b.record_failure()
    b.record_failure()
    assert b.allow_request() is True  # below threshold
    b.record_failure()
    assert b.state.value == "open"
    assert b.allow_request() is False  # fail fast while recovery pending

    time.sleep(1.1)
    # Probe allowed, but only one owner at a time (distributed lock).
    assert b.allow_request() is True
    assert b.state.value == "half_open"
    b.record_success()
    assert b.state.value == "closed"


def test_redis_breaker_state_is_shared_between_workers():
    name = f"test-rd-shared-{uuid.uuid4().hex[:8]}"
    # N workers (A..D) share one Redis-backed view, like N worker processes.
    workers = [
        _redis_breaker(name, failure_threshold=3, recovery_timeout=1.0)
        for _ in range(4)
    ]

    # Every worker contributes a failure; the breaker trips on the Nth one and
    # every worker sees the SAME open state afterwards.
    for i, w in enumerate(workers):
        w.record_failure()
        if i >= 2:  # threshold crossed after the 3rd failure
            assert w.state.value == "open"
        else:
            assert w.state.value == "closed"

    # Every worker (including ones that never saw the trip) fails fast.
    for w in workers:
        assert w.allow_request() is False, "worker must fail fast on shared OPEN"

    # The failure counter is shared: after enough successes the shared state
    # recovers for everyone — verify no worker diverged into a private OPEN.
    for w in workers:
        assert w.snapshot()["failures"] >= 3


def test_redis_breaker_half_open_probe_lock_is_exclusive():
    name = f"test-rd-lock-{uuid.uuid4().hex[:8]}"
    # N workers hit the recovery timeout at roughly the same instant.
    workers = [
        _redis_breaker(name, failure_threshold=2, recovery_timeout=1.0)
        for _ in range(4)
    ]

    for w in workers:
        w.record_failure()
    for w in workers:
        w.record_failure()
    assert all(w.state.value == "open" for w in workers)

    time.sleep(1.1)  # recovery window open

    # All workers race for the HALF_OPEN probe, but the distributed lock lets
    # exactly one through.
    probes = [w.allow_request() for w in workers]
    assert any(probes), "exactly one worker should win the probe"
    assert sum(probes) == 1, f"only one worker may probe, got {sum(probes)}"

    # The winner transitions to HALF_OPEN; everyone else reads the shared
    # HALF_OPEN state too, but their allow_request() returned False (they
    # never acquired the probe lock).
    winner = probes.index(True)
    assert workers[winner].state.value == "half_open"
    for i, w in enumerate(workers):
        if i != winner:
            assert w.state.value == "half_open", "shared state is visible to all"
            assert probes[i] is False, "non-winner must not probe"

    # The prober's success closes it for everyone.
    workers[winner].record_success()
    for w in workers:
        assert w.state.value == "closed"


def test_redis_breaker_falls_back_to_local_when_redis_down(monkeypatch):
    from app.core import redis as redis_module

    name = f"test-rd-fallback-{uuid.uuid4().hex[:8]}"
    b = _redis_breaker(name, failure_threshold=2, recovery_timeout=1.0)
    b.reset()

    monkeypatch.setattr(redis_module.redis_client, "_client", None)
    monkeypatch.setattr(redis_module.redis_client, "_enabled", False)

    # Redis unavailable -> local breaker semantics (still functional).
    assert b.allow_request() is True
    b.record_failure()
    b.record_failure()
    assert b.state.value == "open"


def test_breaker_health_endpoint_reports_redis_state(client, db_session):
    from app.reliability.circuit_breaker import get_breaker

    name = "ollama"
    get_breaker(name).reset()
    res = client.get("/api/v1/analytics/breakers")
    assert res.status_code == 200
    by_name = res.json()
    assert by_name["ollama"]["state"] == "closed"
    assert by_name["ollama"]["backend"] in ("redis", "local")
    assert set(by_name) == {"ollama", "rossko", "smtp", "http"}


# --- Failure classification --------------------------------------------------


def test_classify_exception_maps_http_and_smtp():
    assert classify_exception(httpx.ReadTimeout("t")) is FailureKind.TIMEOUT
    assert classify_exception(httpx.ConnectTimeout("t")) is FailureKind.TIMEOUT
    assert classify_exception(httpx.ConnectError("c")) is FailureKind.UNAVAILABLE
    assert classify_exception(RuntimeError("boom")) is FailureKind.INTERNAL_ERROR

    class _Auth(RuntimeError):
        pass

    assert classify_exception(_Auth("bad key")) is FailureKind.INTERNAL_ERROR  # unknown name


def test_classify_exception_maps_dns_errors():
    import socket

    assert (
        classify_exception(socket.gaierror(socket.EAI_NONAME, "Name or service not known"))
        is FailureKind.UNAVAILABLE
    )
    assert (
        classify_exception(socket.gaierror(socket.EAI_AGAIN, "Temporary failure"))
        is FailureKind.UNAVAILABLE
    )
    # An unrelated OSError (no errno / unknown) stays internal.
    assert classify_exception(OSError(0, "weird")) is FailureKind.INTERNAL_ERROR


def test_classify_exception_respects_explicit_kind():
    error = RuntimeError("SMTP down")
    error.kind = FailureKind.UNAVAILABLE  # type: ignore[attr-defined]
    assert classify_exception(error) is FailureKind.UNAVAILABLE


def test_from_llm_and_supplier_kinds():
    from app.llm.errors import LLMErrorKind
    from app.reliability.errors import from_llm_kind, from_llm_status, from_supplier_kind

    assert from_llm_kind(LLMErrorKind.TIMEOUT) is FailureKind.TIMEOUT
    assert from_llm_kind(LLMErrorKind.ERROR) is FailureKind.INTERNAL_ERROR
    assert from_llm_status("timeout") is FailureKind.TIMEOUT
    assert from_llm_status("authentication") is FailureKind.AUTHENTICATION
    assert from_supplier_kind("connection") is FailureKind.UNAVAILABLE
    assert from_supplier_kind("auth") is FailureKind.AUTHENTICATION
    assert from_supplier_kind("response") is FailureKind.SUPPLIER_ERROR


# --- Replay (sprint 3.5) -----------------------------------------------------


def _task(db, service, title, objective):
    company = db.scalars(select(Company)).first()
    task = service.create(company_id=company.id, title=title, objective=objective)
    db.commit()
    return task


def test_replay_creates_new_task_without_touching_original(db_session):
    service = TaskService(db_session)
    original = _task(db_session, service, "Найти колодки", "Найди тормозные колодки")
    orchestrator.process(db_session, original)
    db_session.refresh(original)
    assert original.status.value == "completed"

    replay = service.replay(original.id)
    db_session.refresh(replay)
    assert replay.id != original.id
    assert replay.replayed_from_task_id == original.id
    assert replay.objective == original.objective
    assert replay.input_data == original.input_data
    assert replay.status.value == "pending"
    assert original.status.value == "completed"  # history untouched
    assert any("Повторно запущено" in e.message for e in replay.events)


def test_replay_rejects_non_terminal_task(db_session):
    from app.models.enums import TaskStatus

    service = TaskService(db_session)
    task = _task(db_session, service, "t", "Найди тормозные колодки")
    task.status = TaskStatus.running
    db_session.commit()
    with pytest.raises(ValueError, match="только завершённую"):
        service.replay(task.id)


def test_replay_depth_guard(db_session, monkeypatch):
    from app.core.config import settings
    from app.models.enums import TaskStatus

    monkeypatch.setattr(settings, "task_max_replay_depth", 3)
    service = TaskService(db_session)
    chain: list[Task] = [_task(db_session, service, "0", "Найди тормозные колодки")]
    for i in range(1, 4):
        task = _task(db_session, service, str(i), "Найди тормозные колодки")
        task.replayed_from_task_id = chain[-1].id
        task.status = TaskStatus.failed
        db_session.commit()
        chain.append(task)

    assert service.replay_depth(chain[-1]) == 3
    with pytest.raises(ValueError, match="повторов"):
        service.replay(chain[-1].id)


def test_replay_links_dead_letter_record(db_session):
    from app.models import DeadTask

    service = TaskService(db_session)
    original = _task(db_session, service, "Отправь письмо", "Отправь письмо клиенту")
    orchestrator.process(db_session, original)
    db_session.refresh(original)
    assert original.status.value == "failed"

    dead = db_session.scalars(
        select(DeadTask).where(DeadTask.task_id == original.id)
    ).first()
    assert dead is not None and dead.replayed_task_id is None

    replay = service.replay(original.id)
    db_session.flush()
    assert dead.replayed_task_id == replay.id


# --- Orchestrator DLQ + bounded retry ----------------------------------------


class _TransientFailingSystem:
    """Replaces SystemAgent: always fails with a transient (unavailable) error."""

    slug = "system-agent"
    name = "SystemAgent"

    def __init__(self, *args, **kwargs):
        pass

    def execute(self, objective, input_data):
        raise httpx.ConnectError("provider unreachable")

    def remember(self, *args, **kwargs):
        pass


def test_transient_task_retries_then_dead_letters(db_session, monkeypatch):
    from app.agents import registry as agents_registry
    from app.core.config import settings
    from app.core.redis import redis_client

    monkeypatch.setitem(agents_registry._AGENT_CLASSES, "system", _TransientFailingSystem)
    monkeypatch.setattr(settings, "task_max_retries", 2)
    saved = redis_client._enabled
    redis_client._enabled = False  # force the inline retry path
    try:
        service = TaskService(db_session)
        task = _task(db_session, service, "нестабильно", "Любая задача")
        orchestrator.process(db_session, task)
        db_session.refresh(task)
    finally:
        redis_client._enabled = saved

    assert task.status.value == "failed"
    assert task.retries == 2
    dead = db_session.scalars(
        select(DeadTask).where(DeadTask.task_id == task.id)
    ).first()
    assert dead is not None
    assert dead.exception_kind == "unavailable"
    assert dead.attempts == 3  # 1 original + 2 retries
    retries = [e for e in task.events if "повтор" in e.message.lower()]
    assert len(retries) == 2


def test_definitive_error_goes_straight_to_dead_letter(db_session):
    from app.core.redis import redis_client

    saved = redis_client._enabled
    redis_client._enabled = False
    try:
        service = TaskService(db_session)
        task = _task(db_session, service, "письмо", "Отправь письмо клиенту")
        orchestrator.process(db_session, task)
        db_session.refresh(task)
    finally:
        redis_client._enabled = saved

    assert task.status.value == "failed"
    assert task.retries == 0
    dead = db_session.scalars(
        select(DeadTask).where(DeadTask.task_id == task.id)
    ).first()
    assert dead is not None
    assert dead.exception_kind == "internal_error"
    assert dead.attempts == 1


def test_llm_breaker_open_fails_fast(db_session, monkeypatch):
    """With the ollama breaker open the LLM client must not call the provider."""
    from app.llm.client import LLMClient

    breaker = get_breaker("ollama")
    for _ in range(settings_breaker_threshold()):
        breaker.record_failure()
    try:
        client = LLMClient()
        client._provider = object()  # pretend a provider exists
        assert client.chat([__import__("app.llm.types", fromlist=["LLMMessage"]).LLMMessage(role="user", content="x")]) is None
        assert client.last_error_kind.value == "unavailable"
    finally:
        breaker.reset()


def settings_breaker_threshold() -> int:
    from app.core.config import settings

    return settings.circuit_breaker_failure_threshold
