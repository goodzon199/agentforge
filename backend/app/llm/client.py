from __future__ import annotations

import threading

from app.core.config import settings
from app.llm.types import LLMMessage, LLMResponse


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
