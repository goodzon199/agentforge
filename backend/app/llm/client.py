from __future__ import annotations

import threading

from app.core.config import settings
from app.llm.cost import estimate_cost_rub, usage_from_response
from app.llm.types import LLMMessage, LLMResponse


class TaskLLMProxy:
    """Wraps an LLM client for the duration of one task (sprint 3.2).

    Forwards ``available`` / ``chat`` / ``embed`` exactly like the inner
    client, but captures the token usage of every call. The orchestrator calls
    ``flush`` when the task finishes to persist LLMUsage rows, which feeds the
    cost/task metric of the agent-quality report.
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
        if response is not None:
            usage = usage_from_response(response)
            used_model = model or getattr(self._inner, "model", None) or ""
            self._usage.append(
                {
                    "model": used_model,
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
        """Persist the recorded calls as LLMUsage rows. Returns row count."""
        from app.models import LLMUsage

        for u in self._usage:
            db.add(
                LLMUsage(
                    company_id=company_id,
                    agent_id=agent_id,
                    task_id=task_id,
                    model=u["model"],
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

    Counts calls/failures since process start; the pilot dashboard
    reports the LLM failure rate from these counters.
    """

    def __init__(self) -> None:
        self._provider = None
        self._lock = threading.Lock()
        self._calls = 0
        self._failures = 0
        if settings.openai_api_key:
            from app.llm.providers.openai_provider import OpenAIProvider

            self._provider = OpenAIProvider(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
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
        if self._provider is None:
            return None
        with self._lock:
            self._calls += 1
        try:
            return self._provider.chat(
                messages=messages,
                model=model or settings.openai_model,
                temperature=temperature if temperature is not None else settings.default_agent_temperature,
                max_tokens=max_tokens,
            )
        except Exception:
            with self._lock:
                self._failures += 1
            return None

    def embed(self, text: str, *, model: str | None = None) -> list[float] | None:
        """Embed a text into a vector. Returns None when unavailable."""
        if self._provider is None:
            return None
        try:
            return self._provider.embed(text=text, model=model or settings.embedding_model)
        except Exception:
            return None


llm_client = LLMClient()
