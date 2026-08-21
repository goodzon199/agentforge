from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer, Order, PartRequest, Vehicle
from app.models.enums import OrderStatus

# Sprint 4.4: customer garage / memory. A customer owns several vehicles and
# carries a memory blob (segment preference, average check, preferences).
# The intake flow reads the garage so a short message like "need an air
# filter" can be matched to the customer's car without re-asking for it.

# Average-check buckets used to label the customer's segment. If no orders yet
# the customer is unlabelled (segment stays "unknown") rather than guessed.
_SEGMENT_BORDERS = (
    (Decimal("20000"), "premium"),
    (Decimal("7000"), "middle"),
)
_DEFAULT_MEMORY = {
    "segment": "unknown",
    "avg_check": None,
    "preferences": {},
}


def _segment_for(avg_check: Decimal | None) -> str:
    if avg_check is None:
        return "unknown"
    for border, segment in _SEGMENT_BORDERS:
        if avg_check >= border:
            return segment
    return "economy"


def _money(value: Any) -> str | None:
    """Render a price as a stable two-decimal string (e.g. '15000.00')."""
    if value is None:
        return None
    try:
        return f"{Decimal(str(value)):.2f}"
    except (TypeError, ValueError, ArithmeticError):
        return str(value)


class CustomerGarageService:
    """Owns the customer's garage (vehicles) and their memory blob."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Memory -------------------------------------------------------------

    def memory(self, customer: Customer) -> dict[str, Any]:
        """The customer memory dict, lazily initialised to defaults."""
        memory = customer.memory or {}
        if not isinstance(memory, dict):
            memory = {}
        for key, value in _DEFAULT_MEMORY.items():
            memory.setdefault(key, value)
        return memory

    def set_preferences(
        self, customer: Customer, preferences: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge free-form preferences into the customer memory."""
        memory = self.memory(customer)
        merged = dict(memory.get("preferences") or {})
        merged.update(preferences)
        memory["preferences"] = merged
        memory["updated_at"] = datetime.now(UTC).isoformat()
        customer.memory = memory
        return memory

    def recompute_average_check(self, customer: Customer) -> dict[str, Any]:
        """Recompute avg_check + segment from non-cancelled orders."""
        memory = self.memory(customer)
        totals = list(
            self.db.scalars(
                select(Order.order_total)
                .where(Order.customer_id == customer.id)
                .where(Order.order_total.isnot(None))
                .where(Order.status != OrderStatus.cancelled)
            )
        )
        avg = None
        if totals:
            avg = sum(totals, Decimal("0")) / len(totals)
        memory["avg_check"] = float(avg) if avg is not None else None
        memory["segment"] = _segment_for(avg)
        memory["avg_check_updated_at"] = datetime.now(UTC).isoformat()
        customer.memory = memory
        return memory

    # --- Garage -------------------------------------------------------------

    def list_vehicles(self, customer: Customer) -> list[Vehicle]:
        stmt = (
            select(Vehicle)
            .where(Vehicle.customer_id == customer.id)
            .order_by(Vehicle.created_at.desc())
        )
        return list(self.db.scalars(stmt).unique().all())

    def get_vehicle(self, vehicle_id: uuid.UUID) -> Vehicle | None:
        return self.db.get(Vehicle, vehicle_id)

    def add_vehicle(
        self,
        customer: Customer,
        *,
        vin: str = "",
        brand: str = "",
        model: str = "",
        year: int | None = None,
        engine: str = "",
        body: str = "",
        registration_number: str = "",
    ) -> Vehicle:
        vehicle = Vehicle(
            company_id=customer.company_id,
            customer_id=customer.id,
            vin=vin,
            brand=brand,
            model=model,
            year=year,
            engine=engine,
            body=body,
            registration_number=registration_number,
        )
        self.db.add(vehicle)
        return vehicle

    def update_vehicle(self, vehicle: Vehicle, **updates: Any) -> Vehicle:
        allowed = {
            "vin", "brand", "model", "year", "engine", "body", "registration_number",
        }
        for key, value in updates.items():
            if key in allowed and value is not None:
                setattr(vehicle, key, value)
        return vehicle

    def delete_vehicle(self, vehicle: Vehicle) -> None:
        # Detach the vehicle from part requests so history is not broken.
        self.db.execute(
            PartRequest.__table__.update()
            .where(PartRequest.vehicle_id == vehicle.id)
            .values(vehicle_id=None)
        )
        self.db.delete(vehicle)

    def default_vehicle(self, customer: Customer) -> Vehicle | None:
        """The car to assume when the customer does not name one.

        Heuristic: prefer the vehicle with the most recent part request
        (the car they last asked about), falling back to the most recently
        created vehicle. Returns None when the garage is empty.
        """
        vehicles = self.list_vehicles(customer)
        if not vehicles:
            return None
        if len(vehicles) == 1:
            return vehicles[0]
        recent = self.db.scalars(
            select(PartRequest.vehicle_id)
            .where(PartRequest.customer_id == customer.id)
            .where(PartRequest.vehicle_id.isnot(None))
            .order_by(PartRequest.created_at.desc())
            .limit(1)
        ).first()
        if recent is not None:
            for vehicle in vehicles:
                if vehicle.id == recent:
                    return vehicle
        return vehicles[0]

    def purchase_history(self, vehicle: Vehicle) -> list[dict[str, Any]]:
        """Orders placed for this car, newest first."""
        rows = list(
            self.db.scalars(
                select(PartRequest)
                .where(PartRequest.vehicle_id == vehicle.id)
                .order_by(PartRequest.created_at.desc())
            ).unique()
        )
        pr_by_id = {pr.id: pr for pr in rows}
        orders = list(
            self.db.scalars(
                select(Order)
                .where(Order.part_request_id.in_(pr_by_id.keys()))
                .order_by(Order.created_at.desc())
            ).unique()
        ) if pr_by_id else []
        history: list[dict[str, Any]] = []
        for order in orders:
            pr = pr_by_id.get(order.part_request_id)
            items = order.items or []
            if items:
                for item in items:
                    history.append(
                        {
                            "order_id": str(order.id),
                            "order_number": order.order_number,
                            "status": order.status.value,
                            "created_at": order.created_at.isoformat(),
                            "part_name": item.get("part_name")
                            or (pr.part_name if pr else ""),
                            "article": item.get("article") or (pr.article if pr else ""),
                            "brand": item.get("brand") or "",
                            "total_price": _money(item.get("total_price")),
                            "quantity": item.get("quantity_available"),
                        }
                    )
            elif pr is not None:
                history.append(
                    {
                        "order_id": str(order.id),
                        "order_number": order.order_number,
                        "status": order.status.value,
                        "created_at": order.created_at.isoformat(),
                        "part_name": pr.part_name,
                        "article": pr.article,
                        "brand": "",
                        "total_price": _money(order.order_total),
                        "quantity": None,
                    }
                )
        return history

    def garage(self, customer: Customer) -> dict[str, Any]:
        """Full garage snapshot: memory + vehicles with purchase history."""
        memory = self.recompute_average_check(customer)
        vehicles = []
        for vehicle in self.list_vehicles(customer):
            vehicles.append(
                {
                    "vehicle": {
                        "id": str(vehicle.id),
                        "vin": vehicle.vin,
                        "brand": vehicle.brand,
                        "model": vehicle.model,
                        "year": vehicle.year,
                        "engine": vehicle.engine,
                        "body": vehicle.body,
                        "registration_number": vehicle.registration_number,
                    },
                    "history": self.purchase_history(vehicle),
                }
            )
        return {
            "customer_id": str(customer.id),
            "memory": memory,
            "vehicles": vehicles,
        }
