from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class SupplierSearchQuery:
    """What we ask a supplier adapter to find."""

    article: str = ""
    part_name: str = ""
    quantity: int = 1
    brand: str = ""
    vehicle_brand: str = ""
    vehicle_model: str = ""
    vehicle_year: int | None = None


@dataclass
class NormalizedSupplierOffer:
    """A supplier offer normalized to the platform contract."""

    supplier_name: str
    brand: str = ""
    article: str = ""
    part_name: str = ""
    purchase_price: Decimal | None = None
    quantity: int | None = None
    delivery_days: int | None = None
    is_cross: bool = False


class SupplierAdapter(ABC):
    """Contract every supplier backend implements.

    ``search`` is async and returns normalized offers; ``healthcheck`` probes
    the backend. A failure in one adapter must never break the whole search,
    so callers treat exceptions as a failed attempt.
    """

    type: str = "base"

    def __init__(
        self, *, name: str = "", settings: dict[str, Any] | None = None
    ) -> None:
        self.name = name
        self.settings = settings or {}

    @abstractmethod
    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        """Return normalized offers matching the query."""

    async def healthcheck(self) -> bool:
        """Best-effort liveness probe of the backend."""
        try:
            offers = await asyncio.wait_for(
                self.search(SupplierSearchQuery(article="")), timeout=5.0
            )
            return True
        except Exception:
            return False
