from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar

from app.suppliers.errors import SupplierQueryNotSupported


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


@dataclass
class SupplierOrderData:
    """What we ask a supplier adapter to purchase (Sprint 4.5).

    ``items`` mirrors the customer-facing order lines (brand/article/quantity)
    plus the internal purchase price each line was quoted at — the supplier
    needs the article and the quantity, the price is carried along for the
    operator's record.
    """

    order_number: str
    items: list[dict[str, Any]]  # [{article, brand, quantity, purchase_price, part_name}]
    delivery_days: int | None = None


@dataclass
class ExternalOrderResult:
    """The supplier's side of a placed purchase order (Sprint 4.5).

    ``external_order_id`` is the supplier's tracking id; ``status`` is the
    supplier-side status at placement time (accepted / shipped / delivered…);
    ``estimated_delivery_days`` lets the platform predict arrival before the
    supplier starts reporting it.
    """

    external_order_id: str
    status: str = "accepted"
    estimated_delivery_days: int | None = None
    message: str = ""


class SupplierAdapter(ABC):
    """Contract every supplier backend implements.

    ``search`` is async and returns normalized offers; ``healthcheck`` probes
    the backend; ``order`` places a purchase and returns the supplier's
    tracking id; ``order_status`` reports its current supplier-side status.
    A failure in one adapter must never break the whole search, so callers
    treat exceptions as a failed attempt.
    """

    type: str = "base"

    # True when the adapter is a preset/skeleton whose endpoint contract has
    # not been verified against a real live API. The platform surfaces this on
    # SupplierRead so operators know such a provider is NOT production-ready.
    experimental: ClassVar[bool] = False

    def __init__(
        self, *, name: str = "", settings: dict[str, Any] | None = None
    ) -> None:
        self.name = name
        self.settings = settings or {}

    @abstractmethod
    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        """Return normalized offers matching the query."""

    async def order(self, *, data: SupplierOrderData) -> ExternalOrderResult:
        """Place a purchase order with the supplier (Sprint 4.5).

        Default: not supported. Live adapters (mock, HTTP) override this; a
        provider that only searches is skipped, never crashed on.
        """
        raise SupplierQueryNotSupported(
            f"Поставщик «{self.name}» не поддерживает размещение заказов."
        )

    async def order_status(self, external_order_id: str) -> str:
        """Poll the supplier-side status of a placed order (Sprint 4.6)."""
        raise SupplierQueryNotSupported(
            f"Поставщик «{self.name}» не поддерживает отслеживание заказов."
        )

    async def healthcheck(self) -> bool:
        """Best-effort liveness probe of the backend."""
        try:
            await asyncio.wait_for(
                self.search(SupplierSearchQuery(article="")), timeout=5.0
            )
            return True
        except Exception:
            return False
