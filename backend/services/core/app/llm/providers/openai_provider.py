from __future__ import annotations

from typing import Any

import httpx

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

    ``timeout`` mirrors the hotfix 3.4.1 budget (connect 5s, read 25s,
    write 10s, pool 5s) so a hung upstream fails fast. ``max_retries`` is kept
    at 0 here: retries are handled by the client so every attempt is visible
    to usage tracking instead of being swallowed inside the SDK.
    """

    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        timeout: httpx.Timeout | float | None = None,
        max_retries: int = 0,
    ) -> None:
        if not _OPENAI_IMPORTABLE:
            raise RuntimeError("The 'openai' package is not installed.")
        if timeout is None:
            timeout = httpx.Timeout(
                connect=5.0, read=25.0, write=10.0, pool=5.0
            )
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

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

    def embed(self, text: str, *, model: str) -> list[float]:
        """Text embedding via the /v1/embeddings endpoint (Ollama-compatible)."""
        resp = self._client.embeddings.create(model=model, input=[text])
        return list(resp.data[0].embedding)
