"""Salon tools for the Beauty pack (sprint 5.5).

Tools are pure-SDK (``shared.tools``): declarative name/description/permissions,
``run(**kwargs) -> ToolResult``. No knowledge of the runtime is required.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar

from shared.tools import Tool, ToolResult

from app.salon import SERVICES, state


class SalonCatalogTool(Tool):
    name = "salon_catalog"
    description = "Список услуг салона с ценой и длительностью."
    permissions: ClassVar[list[str]] = ["customer.read"]

    def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            ok=True,
            data={
                "services": [
                    {
                        "key": s.key,
                        "name": s.name,
                        "duration_min": s.duration_min,
                        "price_rub": s.price_rub,
                        "upsell": s.upsell,
                    }
                    for s in SERVICES.values()
                ]
            },
        )


class CalendarSlotsTool(Tool):
    name = "calendar_slots"
    description = "Найти свободный слот на дату (ISO yyyy-mm-dd) для услуги."
    permissions: ClassVar[list[str]] = ["calendar.read"]

    def run(self, **kwargs: Any) -> ToolResult:
        raw_day = str(kwargs.get("day") or "")
        service_key = str(kwargs.get("service") or "haircut")
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            return ToolResult(ok=False, error=f"Некорректная дата: {raw_day!r}.")
        slot = state.find_free(day, service_key)
        if slot is None:
            return ToolResult(
                ok=False,
                data={"day": raw_day, "service": service_key, "slot": None},
                error="Свободных слотов на эту дату нет.",
            )
        return ToolResult(
            ok=True,
            data={
                "day": raw_day,
                "service": service_key,
                "slot": {
                    "id": slot.id,
                    "day": slot.day.isoformat(),
                    "start": slot.start.strftime("%H:%M"),
                    "master": slot.master,
                },
            },
        )


class CalendarBookTool(Tool):
    name = "calendar_book"
    description = "Забронировать свободный слот за клиентом."
    permissions: ClassVar[list[str]] = ["calendar.write", "booking.create"]

    def run(self, **kwargs: Any) -> ToolResult:
        slot_id = str(kwargs.get("slot_id") or "")
        customer = str(kwargs.get("customer_name") or "").strip()
        service_key = str(kwargs.get("service") or "haircut")
        if not slot_id or not customer:
            return ToolResult(ok=False, error="slot_id и customer_name обязательны.")
        booking = state.book(slot_id, customer, service_key)
        if booking is None:
            return ToolResult(ok=False, error="Слот не найден или уже занят.")
        return ToolResult(
            ok=True,
            data={
                "booking_id": booking.id,
                "slot_id": booking.slot_id,
                "customer_name": booking.customer_name,
                "service": booking.service_key,
                "master": booking.master,
                "day": booking.day.isoformat(),
                "start": booking.start.strftime("%H:%M"),
            },
        )


class ReminderScheduleTool(Tool):
    name = "reminder_schedule"
    description = "Назначить напоминание о визите за N часов до записи."
    permissions: ClassVar[list[str]] = ["notification.send"]

    def run(self, **kwargs: Any) -> ToolResult:
        booking_id = str(kwargs.get("booking_id") or "")
        hours_before = int(kwargs.get("hours_before") or 3)
        booking = state.get_booking(booking_id)
        if booking is None:
            return ToolResult(ok=False, error="Запись не найдена.")
        state.schedule_reminder(booking.id, hours_before)
        return ToolResult(
            ok=True,
            data={
                "booking_id": booking.id,
                "reminder_hours_before": hours_before,
                "reminder_at": (
                    f"{booking.day.isoformat()} "
                    f"{booking.start.strftime('%H:%M')}"
                ),
            },
        )
