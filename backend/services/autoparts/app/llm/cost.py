from __future__ import annotations

from decimal import Decimal

from app.llm.types import LLMResponse


def estimate_cost_rub(model: str, prompt_tokens: int, completion_tokens: int) -> Decimal:
    """Estimate an LLM call cost in rubles from token usage (sprint 3.2).

    Prices live in settings (RUB per 1M tokens per model). Unknown models —
    e.g. local Ollama — are treated as free, so the pilot shows real money
    only where the operator actually pays for tokens.
    """
    from app.core.config import settings

    input_price = settings.llm_price_rub_per_1m_input.get(model, 0.0)
    output_price = settings.llm_price_rub_per_1m_output.get(model, 0.0)
    cost = (
        (prompt_tokens / 1_000_000) * input_price
        + (completion_tokens / 1_000_000) * output_price
    )
    return Decimal(str(round(cost, 4)))


def usage_from_response(response: LLMResponse | None) -> dict[str, int]:
    """Extract token usage from an LLM response (OpenAI-compatible ``usage``)."""
    if response is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage = (response.raw or {}).get("usage") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }
