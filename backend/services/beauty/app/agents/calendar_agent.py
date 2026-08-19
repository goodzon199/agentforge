"""CalendarAgent (sprint 5.5): find a free slot for a requested day/service."""

from __future__ import annotations

from typing import ClassVar

from shared.agents import AgentContext, AgentOutput

from app.agents.base import BeautyAgent


class CalendarAgent(BeautyAgent):
    kind = "calendar"
    name = "CalendarAgent"
    description = "Находит свободный слот салона на нужную дату."
    permissions: ClassVar[list[str]] = ["calendar.read"]

    def execute(self, ctx: AgentContext) -> AgentOutput:
        input_data = ctx.input_data or {}
        day = input_data.get("day")
        service_key = input_data.get("service") or "haircut"
        if not day:
            return AgentOutput(
                response="Не указана дата для поиска слота.",
                data={"slot_found": False},
                routing_decision={
                    "needs_agent": None,
                    "reason": "no_day",
                    "engine": "calendar",
                },
            )

        result = ctx.tools.run("calendar_slots", day=day, service=service_key)
        slot = (result.data or {}).get("slot") if result.ok else None

        if ctx.actions is not None:
            ctx.actions.record(
                "calendar.find_slot",
                target_type="slot",
                input_data={"day": day, "service": service_key},
                result_data={"found": slot is not None},
            )

        if not result.ok or slot is None:
            return AgentOutput(
                response=result.error or "Свободных слотов на эту дату нет.",
                data={"slot_found": False, "day": day, "service": service_key},
                routing_decision={
                    "needs_agent": None,
                    "reason": "no_slot",
                    "engine": "calendar",
                },
            )

        return AgentOutput(
            response=(
                f"Нашёл свободный слот {slot['day']} в {slot['start']} "
                f"(мастер {slot['master']})."
            ),
            data={
                "slot_found": True,
                "slot": slot,
                "day": day,
                "service": service_key,
            },
            routing_decision={
                "needs_agent": None,
                "reason": "slot_found",
                "engine": "calendar",
            },
        )
