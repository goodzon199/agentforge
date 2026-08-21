"""Salon domain for the Beauty pack (sprint 5.5).

Pure in-memory model — no database. A pack vertical does not need its own
storage to run: the SDK contract and the pack's own domain services are
enough. State resets on process restart, which is fine for a demo vertical.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, time

# --- Catalog ----------------------------------------------------------------


@dataclass(frozen=True)
class Service:
    key: str
    name: str
    duration_min: int
    price_rub: int
    upsell: str | None = None


SERVICES: dict[str, Service] = {
    "haircut": Service("haircut", "Стрижка", 60, 1500, "укладка (+800 ₽)"),
    "coloring": Service("coloring", "Окрашивание", 150, 4500, "уход после окрашивания (+1200 ₽)"),
    "manicure": Service("manicure", "Маникюр", 60, 1800, "покрытие гель-лак (+900 ₽)"),
    "pedicure": Service("pedicure", "Педикюр", 90, 2500, "парафинотерапия (+700 ₽)"),
}

MASTERS = ["Анна", "Мария", "Ольга"]
OPEN_HOUR = 9
CLOSE_HOUR = 20
SLOT_MINUTES = 60


# --- Calendar ---------------------------------------------------------------


@dataclass
class Slot:
    id: str
    day: date
    start: time
    master: str
    service_key: str
    booked: bool = False


@dataclass
class Booking:
    id: str
    slot_id: str
    customer_name: str
    service_key: str
    master: str
    day: date
    start: time
    upsell_taken: str | None = None
    reminder_hours_before: int = 3


class SalonState:
    """Thread-unsafe in-memory calendar. Guarded by the app lock when used
    from the FastAPI endpoints (see salon.py::lock)."""

    def __init__(self) -> None:
        self._slots: list[Slot] = []
        self._bookings: dict[str, Booking] = {}

    # --- build / query -----------------------------------------------------

    def ensure_slots(self, day: date) -> list[Slot]:
        """Generate SLOT_MINUTES slots for every master if not yet present."""
        for master in MASTERS:
            for hour in range(OPEN_HOUR, CLOSE_HOUR):
                start = time(hour=hour, minute=0)
                if not any(
                    s.day == day and s.start == start and s.master == master
                    for s in self._slots
                ):
                    self._slots.append(
                        Slot(
                            id=str(uuid.uuid4()),
                            day=day,
                            start=start,
                            master=master,
                            service_key="any",
                        )
                    )
        return [s for s in self._slots if s.day == day]

    def free_slots(self, day: date) -> list[Slot]:
        self.ensure_slots(day)
        return [s for s in self._slots if s.day == day and not s.booked]

    def find_free(self, day: date, service_key: str) -> Slot | None:
        """First free slot on the day (service-agnostic masters)."""
        free = self.free_slots(day)
        if not free:
            return None
        free.sort(key=lambda s: (s.start, s.master))
        return free[0]

    def get_slot(self, slot_id: str) -> Slot | None:
        return next((s for s in self._slots if s.id == slot_id), None)

    # --- mutations ---------------------------------------------------------

    def book(self, slot_id: str, customer_name: str, service_key: str) -> Booking | None:
        slot = self.get_slot(slot_id)
        if slot is None or slot.booked:
            return None
        slot.booked = True
        booking = Booking(
            id=str(uuid.uuid4()),
            slot_id=slot.id,
            customer_name=customer_name,
            service_key=service_key,
            master=slot.master,
            day=slot.day,
            start=slot.start,
        )
        self._bookings[booking.id] = booking
        return booking

    def get_booking(self, booking_id: str) -> Booking | None:
        return self._bookings.get(booking_id)

    def attach_upsell(self, booking_id: str, upsell: str) -> Booking | None:
        booking = self.get_booking(booking_id)
        if booking is None:
            return None
        booking.upsell_taken = upsell
        return booking

    def schedule_reminder(self, booking_id: str, hours_before: int) -> Booking | None:
        booking = self.get_booking(booking_id)
        if booking is None:
            return None
        booking.reminder_hours_before = hours_before
        return booking


state = SalonState()
