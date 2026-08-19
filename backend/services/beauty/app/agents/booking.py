"""BookingAgent (sprint 5.5): book a found slot for the customer."""

from __future__ import annotations

from typing import ClassVar

from shared.agents import AgentContext, AgentOutput

from app.agents.base import BeautyAgent


class BookingAgent(BeautyAgent):
    kind = "booking"
    name = "BookingAgent"
    description = "Бронирует найденный слот за клиентом."
    permissions: ClassVar[list[str]] = ["calendar.write", "booking.create"]

    def execute(self, ctx: AgentContext) -> AgentOutput:
        input_data = ctx.input_data or {}
        slot = input_data.get("slot") or {}
        customer = input_data.get("customer_name") or "Клиент"
        service_key = input_data.get("service") or "haircut"

        ctx.permissions.require("calendar.write", "booking.create")

        slot_id = slot.get("id")
        if not slot_id:
            return AgentOutput(
                response="Нет слота для бронирования.",
                data={"booking_id": None},
                routing_decision={
                    "needs_agent": None,
                    "reason": "no_slot",
                    "engine": "booking",
                },
            )

        result = ctx.tools.run(
            "calendar_book",
            slot_id=slot_id,
            customer_name=customer,
            service=service_key,
        )
        booking = result.data if result.ok else None

        if ctx.actions is not None:
            ctx.actions.record(
                "booking.create",
                target_type="booking",
                target_id=(booking or {}).get("booking_id"),
                input_data={"slot_id": slot_id, "customer_name": customer},
                result_data={"ok": result.ok, "error": result.error},
                risk_level="low",
            )

        if not result.ok or booking is None:
            return AgentOutput(
                response=result.error or "Не удалось забронировать слот.",
                data={"booking_id": None},
                routing_decision={
                    "needs_agent": None,
                    "reason": "book_failed",
                    "engine": "booking",
                },
            )

        return AgentOutput(
            response=(
                f"Записал {customer} на {booking['day']} в {booking['start']} "
                f"(мастер {booking['master']}). Номер записи {booking['booking_id']}."
            ),
            data={"booking": booking, "booking_id": booking["booking_id"]},
            routing_decision={
                "needs_agent": None,
                "reason": "booked",
                "engine": "booking",
            },
        )
