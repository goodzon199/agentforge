"""ReminderAgent (sprint 5.5): schedule a reminder for the visit."""

from __future__ import annotations

from typing import ClassVar

from shared.agents import AgentContext, AgentOutput

from app.agents.base import BeautyAgent


class ReminderAgent(BeautyAgent):
    kind = "reminder"
    name = "ReminderAgent"
    description = "Назначает напоминание о визите за N часов до записи."
    permissions: ClassVar[list[str]] = ["notification.send"]

    def execute(self, ctx: AgentContext) -> AgentOutput:
        input_data = ctx.input_data or {}
        booking = input_data.get("booking") or {}
        hours_before = int(input_data.get("reminder_hours_before") or 3)

        ctx.permissions.require("notification.send")

        booking_id = booking.get("booking_id")
        if not booking_id:
            return AgentOutput(
                response="Нет записи для напоминания.",
                data={"reminder": None},
                routing_decision={
                    "needs_agent": None,
                    "reason": "no_booking",
                    "engine": "reminder",
                },
            )

        result = ctx.tools.run(
            "reminder_schedule",
            booking_id=booking_id,
            hours_before=hours_before,
        )
        reminder = result.data if result.ok else None

        if ctx.actions is not None:
            ctx.actions.record(
                "reminder.schedule",
                target_type="booking",
                target_id=booking_id,
                input_data={"hours_before": hours_before},
                result_data={"ok": result.ok, "error": result.error},
            )

        if not result.ok or reminder is None:
            return AgentOutput(
                response=result.error or "Не удалось назначить напоминание.",
                data={"reminder": None},
                routing_decision={
                    "needs_agent": None,
                    "reason": "reminder_failed",
                    "engine": "reminder",
                },
            )

        return AgentOutput(
            response=(
                f"Напомню о визите за {hours_before} ч. "
                f"(запись {reminder['booking_id']})."
            ),
            data={"reminder": reminder},
            routing_decision={
                "needs_agent": None,
                "reason": "reminder_set",
                "engine": "reminder",
            },
        )
