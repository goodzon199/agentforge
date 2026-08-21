from __future__ import annotations

from abc import ABC, abstractmethod

from app.llm.types import LLMMessage, LLMResponse


class BaseLLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
