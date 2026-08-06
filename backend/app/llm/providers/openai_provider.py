from __future__ import annotations

from typing import Any

from app.llm.providers.base import BaseLLMProvider
from app.llm.types import LLMMessage, LLMResponse

try:
    from openai import OpenAI

    _OPENAI_IMPORTABLE = True
except ImportError:  # pragma: no cover
    _OPENAI_IMPORTABLE = False


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI / compatible (Azure, Ollama via /v1, local) chat provider.
    """

    name = "openai"

    def __init__(self, api_key: str, base_url: str) -> None:
        if not _OPENAI_IMPORTABLE:
            raise RuntimeError("The 'openai' package is not installed.")
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": [m.model_dump() for m in messages],
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        completion = self._client.chat.completions.create(**payload)
        content = completion.choices[0].message.content or ""
        return LLMResponse(content=content, model=model, raw=completion.model_dump())
