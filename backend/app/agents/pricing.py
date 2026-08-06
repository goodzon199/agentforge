from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from app.agents.base import AgentOutput, BaseAgent
from app.models import PartRequest
from app.services.pricing_service import PricingService


def _money(value: str | None) -> str:
    if not value:
        return "—"
    amount = Decimal(value)
    if amount == amount.to_integral():
        text = f"{int(amount):,}"
    else:
        text = f"{amount:,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ")


class PricingAgent(BaseAgent):
    """Runs the pricing step of the parts pipeline for ``pricing_parts`` tasks.

    It reads the offers of the search run referenced in ``input_data``,
    computes customer-facing prices (margin over purchase price) and stores
    the quote on the part request.
    """

    kind = "pricing"

    def execute(self, objective: str, input_data: dict[str, Any]) -> AgentOutput:
        if self.db is None:
            return AgentOutput(
                response="Расчёт цены недоступен без базы данных.",
                data={"action": "pricing_parts_error", "reason": "db_missing"},
                routing_decision={
                    "needs_agent": None,
                    "reason": "db_missing",
                    "engine": "pricing",
                },
            )

        raw_part_request_id = input_data.get("part_request_id")
        if not raw_part_request_id:
            return AgentOutput(
                response="Не указана заявка для расчёта цены.",
                data={
                    "action": "pricing_parts_error",
                    "reason": "missing_part_request_id",
                },
                routing_decision={
                    "needs_agent": None,
                    "reason": "missing_part_request_id",
                    "engine": "pricing",
                },
            )

        try:
            part_request_id = uuid.UUID(str(raw_part_request_id))
            raw_run_id = input_data.get("run_id")
            run_id = uuid.UUID(str(raw_run_id)) if raw_run_id else None
        except (ValueError, TypeError):
            return AgentOutput(
                response="Некорректный идентификатор заявки или поиска.",
                data={"action": "pricing_parts_error", "reason": "invalid_id"},
                routing_decision={
                    "needs_agent": None,
                    "reason": "invalid_id",
                    "engine": "pricing",
                },
            )

        if self.db.get(PartRequest, part_request_id) is None:
            return AgentOutput(
                response="Заявка на запчасть не найдена.",
                data={"action": "pricing_parts_error", "reason": "not_found"},
                routing_decision={
                    "needs_agent": None,
                    "reason": "not_found",
                    "engine": "pricing",
                },
            )

        summary = PricingService(self.db).process(
            part_request_id, run_id=run_id, triggered_by="agent"
        )
        self.db.commit()

        return AgentOutput(
            response=self._response(summary),
            data={"action": "pricing_parts", **summary},
            routing_decision={
                "needs_agent": None,
                "reason": "Цена рассчитана PricingAgent по предложениям поставщиков.",
                "engine": "pricing",
            },
            handoff_agent=None,
        )

    @staticmethod
    def _response(summary: dict[str, Any]) -> str:
        status = summary.get("status")
        if status == "no_run":
            return "Не найдено результатов поиска для расчёта цены."
        if status == "no_offers":
            return "Предложений для расчёта цены нет — заявка вернулась к поиску."
        margin = summary.get("margin_percent")
        qty = summary.get("quantity", 1)
        suffix = f" (наценка {margin:g}%)." if margin is not None else "."
        return (
            f"Цена рассчитана: {summary.get('best_brand') or '—'} "
            f"{summary.get('best_article') or '—'} — "
            f"{_money(summary.get('best_unit_price'))} ₽/шт × {qty} = "
            f"{_money(summary.get('best_total_price'))} ₽"
            f"{suffix}"
        )
