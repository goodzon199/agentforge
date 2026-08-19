"""ReceptionAgent (sprint 5.5): first line of the booking pipeline.

Takes a free-form customer request and extracts the requested service and
desired date. Deterministic keyword matching over the salon catalog; no LLM
dependency so the pack works offline.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, ClassVar

from shared.agents import AgentContext, AgentOutput

from app.agents.base import BeautyAgent
from app.salon import SERVICES

_SERVICE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("haircut", ("стрижк", "подстри", "haircut")),
    ("coloring", ("окрашиван", "покрас", "color", "тон")),
    ("manicure", ("маникюр", "manicure", "ногт")),
    ("pedicure", ("педикюр", "pedicure")),
]

_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


class ReceptionAgent(BeautyAgent):
    kind = "reception"
    name = "ReceptionAgent"
    description = "Принимает заявку клиента: распознаёт услугу и желаемую дату."
    permissions: ClassVar[list[str]] = ["customer.read"]

    def execute(self, ctx: AgentContext) -> AgentOutput:
        objective = ctx.objective or ""
        input_data = ctx.input_data or {}

        service_key = self._service(objective)
        day = self._date(objective, input_data)

        data: dict[str, Any] = {
            "service": service_key,
            "service_name": SERVICES[service_key].name if service_key else None,
            "day": day.isoformat() if day else None,
            "has_service": bool(service_key),
            "has_date": day is not None,
        }
        if ctx.memory is not None:
            ctx.memory.remember(
                f"Заявка: {objective[:80]} -> услуга={service_key}, дата={day}",
                kind="reception",
            )
        if ctx.actions is not None:
            ctx.actions.record(
                "reception.parse",
                input_data={"objective": objective[:200]},
                result_data=data,
            )

        if not service_key and day is None:
            response = "Не удалось распознать ни услугу, ни дату. Уточните, пожалуйста."
        elif not service_key:
            response = "Уточните, какую услугу вы хотите (стрижка, окрашивание, маникюр, педикюр)."
        elif day is None:
            response = f"На какую дату хотите «{SERVICES[service_key].name}»? (формат ГГГГ-ММ-ДД)"
        else:
            response = (
                f"Принято: «{SERVICES[service_key].name}» на {day.isoformat()}. "
                f"Ищу свободный слот."
            )
        return AgentOutput(
            response=response,
            data=data,
            routing_decision={
                "needs_agent": None,
                "reason": "Заявка разобрана, передаю дальше по конвейеру.",
                "engine": "rules",
            },
        )

    @staticmethod
    def _service(objective: str) -> str | None:
        text = objective.lower()
        for key, keywords in _SERVICE_KEYWORDS:
            if any(kw in text for kw in keywords):
                return key
        return None

    @staticmethod
    def _date(objective: str, input_data: dict[str, Any]) -> date | None:
        raw = input_data.get("day") or input_data.get("date")
        if raw:
            try:
                return date.fromisoformat(str(raw))
            except ValueError:
                pass
        match = _DATE_RE.search(objective)
        if match:
            try:
                return date.fromisoformat(match.group(1))
            except ValueError:
                return None
        return None
