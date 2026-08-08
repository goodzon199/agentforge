from __future__ import annotations

import threading
import time

from sqlalchemy import func, select

from app.core.config import settings
from app.llm.cost import estimate_cost_rub, usage_from_response
from app.llm.errors import LLMErrorKind, classify_exception, classify_response
from app.llm.types import LLMMessage, LLMResponse
from app.reliability.circuit_breaker import get_breaker
from app.reliability.errors import TRANSIENT, from_llm_kind
from app.reliability.retry import get_policy


class TaskLLMProxy:
    """Wraps an LLM client for the duration of one task (sprint 3.2).

    Forwards ``available`` / ``chat`` / ``embed`` exactly like the inner
    client, but captures the usage of *every attempt* — successful and failed
    alike — with a normalized status code (ok/timeout/unavailable/rate_limited/
    invalid_response/error). The orchestrator calls ``flush`` when the task
    finishes to persist LLMUsage rows, which feed the cost/task metric and the
    per-agent ``total_llm_calls`` counter (source of truth = LLMUsage).
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self._usage: list[dict] = []

    @property
    def available(self) -> bool:
        return bool(getattr(self._inner, "available", False))

    @property
    def model(self) -> str | None:
        return getattr(self._inner, "model", None)

    @property
    def stats(self) -> dict[str, int]:
        return getattr(self._inner, "stats", {"calls": 0, "failures": 0})

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse | None:
        response = self._inner.chat(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        used_model = (
            model
            or getattr(self._inner, "model", None)
            or settings.openai_model
            or ""
        )
        attempts = getattr(self._inner, "last_attempts", None) or [
            {"status": LLMErrorKind.ERROR.value, "duration_ms": 0}
        ]
        success_usage = usage_from_response(response)
        last_index = len(attempts) - 1
        for index, attempt in enumerate(attempts):
            has_tokens = response is not None and index == last_index
            usage = success_usage if has_tokens else {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            self._usage.append(
                {
                    "model": used_model,
                    "status": attempt.get("status", LLMErrorKind.ERROR.value),
                    "duration_ms": attempt.get("duration_ms", 0),
                    **usage,
                    "cost_rub": estimate_cost_rub(
                        used_model,
                        usage["prompt_tokens"],
                        usage["completion_tokens"],
                    ),
                }
            )
        return response

    def embed(self, text: str, *, model: str | None = None) -> list[float] | None:
        return self._inner.embed(text=text, model=model)

    def flush(
        self,
        db,
        *,
        task_id,
        company_id=None,
        agent_id=None,
    ) -> int:
        """Persist the recorded attempts as LLMUsage rows. Returns row count.

        Idempotent per task: a re-processed task (watchdog replay, manual
        retry) does not duplicate rows, so agent statistics are not inflated
        by a second execution.
        """
        from app.models import LLMUsage

        if not self._usage:
            return 0
        existing = db.scalar(
            select(func.count()).select_from(LLMUsage).where(LLMUsage.task_id == task_id)
        )
        if existing:
            return 0
        for u in self._usage:
            db.add(
                LLMUsage(
                    company_id=company_id,
                    agent_id=agent_id,
                    task_id=task_id,
                    model=u["model"],
                    status=u["status"],
                    duration_ms=u["duration_ms"],
                    prompt_tokens=u["prompt_tokens"],
                    completion_tokens=u["completion_tokens"],
                    total_tokens=u["total_tokens"],
                    estimated_cost_rub=u["cost_rub"],
                )
            )
        return len(self._usage)


class LLMClient:
    """
    Facade over LLM providers. Falls back to a deterministic
    rule engine when no provider is configured, so the platform
    always stays runnable.

    Every attempt (including retries of transient errors) is recorded in
    ``last_attempts`` with a normalized status so the per-task proxy can track
    usage faithfully. Counts calls/failures since process start; the pilot
    dashboard reports the LLM failure rate from these counters.
    """

    def __init__(self) -> None:
        self._provider = None
        self._lock = threading.Lock()
        self._calls = 0
        self._failures = 0
        self.model = settings.openai_model or None
        self.last_attempts: list[dict] = []
        self.last_error_kind: LLMErrorKind | None = None
        if settings.openai_api_key:
            import httpx

            from app.llm.providers.openai_provider import OpenAIProvider

            self._provider = OpenAIProvider(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                timeout=httpx.Timeout(
                    connect=settings.llm_connect_timeout,
                    read=settings.llm_read_timeout,
                    write=settings.llm_write_timeout,
                    pool=settings.llm_pool_timeout,
                ),
                max_retries=0,
            )

    @property
    def available(self) -> bool:
        return self._provider is not None

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"calls": self._calls, "failures": self._failures}

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse | None:
        self.last_attempts = []
        self.last_error_kind = None

        if self._provider is None:
            self.last_attempts = [
                {"status": LLMErrorKind.UNAVAILABLE.value, "duration_ms": 0}
            ]
            self.last_error_kind = LLMErrorKind.UNAVAILABLE
            return None

        # Circuit breaker "ollama": when open we fail fast instead of burning
        # a worker thread waiting for a timeout on a dead provider.
        breaker = get_breaker("ollama")
        if not breaker.allow_request():
            self.last_attempts = [
                {"status": LLMErrorKind.UNAVAILABLE.value, "duration_ms": 0}
            ]
            self.last_error_kind = LLMErrorKind.UNAVAILABLE
            return None

        model = model or self.model or settings.openai_model
        temperature = (
            temperature
            if temperature is not None
            else settings.default_agent_temperature
        )
        policy = get_policy("llm")
        for attempt in range(1, policy.max_attempts + 1):
            started = time.monotonic()
            with self._lock:
                self._calls += 1
            try:
                response = self._provider.chat(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                kind = classify_response(response)
            except Exception as exc:  # noqa: BLE001 - classify every failure
                kind = classify_exception(exc)
                response = None
                with self._lock:
                    self._failures += 1
            self.last_attempts.append(
                {
                    "status": kind.value,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                }
            )
            self.last_error_kind = kind
            if kind is LLMErrorKind.OK:
                breaker.record_success()
                return response
            if policy.should_retry(from_llm_kind(kind), attempt):
                time.sleep(policy.next_delay(attempt))
                continue
            break
        if from_llm_kind(self.last_error_kind) in TRANSIENT:
            breaker.record_failure()
        return None

    def embed(self, text: str, *, model: str | None = None) -> list[float] | None:
        """Embed a text into a vector. Returns None when unavailable."""
        if self._provider is None:
            return None
        if not get_breaker("ollama").allow_request():
            return None
        try:
            result = self._provider.embed(
                text=text, model=model or settings.embedding_model
            )
            get_breaker("ollama").record_success()
            return result
        except Exception:
            get_breaker("ollama").record_failure()
            return None


llm_client = LLMClient()
