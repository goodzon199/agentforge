from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class LLMError(RuntimeError):
    pass


class LLMMessage(BaseModel):
    role: str  # system | user | assistant
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    raw: dict[str, Any] | None = None
