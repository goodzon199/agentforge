from __future__ import annotations

import uuid
from typing import Any

from app.agents.base import AgentOutput, BaseAgent
from app.models import Quote
from app.services.sales_service import SalesService


class SalesAgent(BaseAgent):
    """Prepares a customer-facing offer message from a ready Quote.

    SalesAgent does NOT search parts, does NOT compute prices and does NOT
    change them — it only rephrases the facts the system has already computed.
    Every draft it produces goes through QuoteGuard; a draft that contradicts
    the quote is replaced with the deterministic system template.
    """

    kind = "sales"

    def execute(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        raw_quote_id = input_data.get("quote_id")
        if not raw_quote_id:
            return AgentOutput(
                response="Не указана квота для подготовки предложения.",
                data={"action": "sales_draft_error", "reason": "missing_quote_id"},
                routing_decision={
                    "needs_agent": None,
                    "reason": "missing_quote_id",
                    "engine": "sales",
                },
            )
        try:
            quote_id = uuid.UUID(str(raw_quote_id))
        except (ValueError, TypeError):
            return AgentOutput(
                response="Некорректный идентификатор квоты.",
                data={"action": "sales_draft_error", "reason": "invalid_id"},
                routing_decision={
                    "needs_agent": None,
                    "reason": "invalid_id",
                    "engine": "sales",
                },
            )

        quote = self.db.get(Quote, quote_id) if self.db is not None else None
        if quote is None:
            return AgentOutput(
                response="Квота не найдена.",
                data={"action": "sales_draft_error", "reason": "not_found"},
                routing_decision={
                    "needs_agent": None,
                    "reason": "not_found",
                    "engine": "sales",
                },
            )

        result = SalesService(self.db).generate_draft(
            quote,
            agent_record=self.record,
            llm=self.llm,
        )
        self.db.commit()

        message = result.get("message", "")
        guard = result.get("guard", {})
        return AgentOutput(
            response=message,
            data={
                "action": "sales_draft",
                "quote_id": str(quote.id),
                "draft": message,
                "guard": guard,
                "recommended_offer_id": result.get("recommended_offer_id"),
                "reason": result.get("reason"),
            },
            routing_decision={
                "needs_agent": None,
                "reason": "Предложение подготовлено SalesAgent по готовой квоте.",
                "engine": "sales",
            },
            handoff_agent=None,
        )
