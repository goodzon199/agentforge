from __future__ import annotations

from app.core.config import settings
from app.llm.types import LLMMessage, LLMResponse


class LLMClient:
    """
    Facade over LLM providers. Falls back to a deterministic
    rule engine when no provider is configured, so the platform
    always stays runnable.
    """

    def __init__(self) -> None:
        self._provider = None
        if settings.openai_api_key:
            from app.llm.providers.openai_provider import OpenAIProvider

            self._provider = OpenAIProvider(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )

    @property
    def available(self) -> bool:
        return self._provider is not None

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
        return self._provider.chat(
            messages=messages,
            model=model or settings.openai_model,
            temperature=temperature if temperature is not None else settings.default_agent_temperature,
            max_tokens=max_tokens,
        )


llm_client = LLMClient()
