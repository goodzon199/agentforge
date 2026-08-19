"""SalesAgent (sprint 5.5): propose an upsell and confirm the booking.

Runs after BookingAgent: takes the confirmed booking, looks up the service
upsell from the catalog and returns a customer-facing confirmation with the
optional add-on. Never changes the booking — only presents facts.
"""

from __future__ import annotations

from typing import ClassVar

from shared.agents import AgentContext, AgentOutput

from app.agents.base import BeautyAgent
from app.salon import SERVICES


class SalesAgent(BeautyAgent):
    kind = "sales"
    name = "SalesAgent"
    description = "Подтверждает запись и предлагает доп. услуги."
    permissions: ClassVar[list[str]] = ["customer.read"]

    def execute(self, ctx: AgentContext) -> AgentOutput:
        input_data = ctx.input_data or {}
        booking = input_data.get("booking") or {}
        service_key = booking.get("service") or "haircut"
        service = SERVICES.get(service_key)

        upsell = service.upsell if service else None
        price = service.price_rub if service else None

        if ctx.actions is not None:
            ctx.actions.record(
                "sales.confirm_booking",
                target_type="booking",
                target_id=booking.get("booking_id"),
                input_data={"service": service_key},
                result_data={"upsell": upsell, "price": price},
            )

        response = (
            f"Запись подтверждена: {booking.get('service') or service_key} "
            f"{booking.get('day')} в {booking.get('start')}, "
            f"мастер {booking.get('master')}. Стоимость {price} ₽."
        )
        if upsell:
            response += f" Могу добавить: {upsell}."
        return AgentOutput(
            response=response,
            data={
                "confirmation": response,
                "upsell": upsell,
                "price": price,
                "booking_id": booking.get("booking_id"),
            },
            routing_decision={
                "needs_agent": None,
                "reason": "confirmed",
                "engine": "sales",
            },
        )
