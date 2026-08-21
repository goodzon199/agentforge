from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any, ClassVar

from app.suppliers.base import (
    ExternalOrderResult,
    NormalizedSupplierOffer,
    SupplierAdapter,
    SupplierOrderData,
    SupplierSearchQuery,
)
from app.suppliers.normalize import normalize_article

# In-process ledger of placed mock orders: external_order_id -> state.
# Survives across adapter instances (each request builds a fresh adapter) so
# order_status() can track an order placed earlier in the process.
_MOCK_ORDERS: dict[str, dict[str, Any]] = {}


class MockSupplierAdapter(SupplierAdapter):
    """Stable, deterministic demo supplier.

    Serves a small fixed catalog (brake pads). Filters by article when given;
    otherwise matches the query text against per-item keywords so a request for
    oil does not return pads. Used as the default demo adapter and as a fixture
    in tests. Real parts (e.g. engine oil) must come from live suppliers such as
    Rossko so prices are genuine.
    """

    type = "mock"

    CATALOG: ClassVar[list[tuple[str, str, str, str, int, int, tuple[str, ...]]]] = [
        # (brand, article, part_name, price, quantity, delivery_days, keywords)
        ("BREMBO", "P06089", "Тормозные колодки передние", "6800.00", 4, 2, ("колодк", "тормозн")),
        ("TRW", "GDB2119", "Тормозные колодки передние", "6100.00", 3, 1, ("колодк", "тормозн")),
    ]

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        article = normalize_article(query.article)
        text = f"{query.part_name} {query.brand}".strip().lower()
        offers: list[NormalizedSupplierOffer] = []
        for brand, art, name, price, qty, days, keywords in self.CATALOG:
            if article and not self._matches(article, normalize_article(art)):
                continue
            if not article and text and not any(kw in text for kw in keywords):
                continue
            offers.append(
                NormalizedSupplierOffer(
                    supplier_name=self.name,
                    brand=brand,
                    article=art,
                    part_name=name,
                    purchase_price=Decimal(price),
                    quantity=qty,
                    delivery_days=days,
                )
            )
        return offers

    async def order(self, *, data: SupplierOrderData) -> ExternalOrderResult:
        """Place a fake purchase: assign a tracking id and open a timeline.

        The mock simulates the supplier lifecycle deterministically: an order
        is "accepted" immediately and advances to "shipped" / "delivered" as
        real time passes (per the quoted delivery days), so order tracking and
        the customer "your order arrived" notification work against a live
        demo without any external system.
        """
        external_order_id = f"EXT-{data.order_number}-{uuid.uuid4().hex[:6].upper()}"
        days = data.delivery_days
        if days is None:
            days = max(
                (
                    int(it.get("delivery_days") or 0)
                    for it in data.items
                    if it.get("delivery_days") is not None
                ),
                default=1,
            )
        _MOCK_ORDERS[external_order_id] = {
            "order_number": data.order_number,
            "placed_at": time.time(),
            "delivery_days": max(days, 1),
            "status": "accepted",
        }
        return ExternalOrderResult(
            external_order_id=external_order_id,
            status="accepted",
            estimated_delivery_days=max(days, 1),
            message=f"Заказ {data.order_number} принят поставщиком.",
        )

    async def order_status(self, external_order_id: str) -> str:
        state = _MOCK_ORDERS.get(external_order_id)
        if state is None:
            return "unknown"
        elapsed = time.time() - state["placed_at"]
        window = state["delivery_days"] * 86400
        # The supplier lifecycle: accepted -> assembling -> shipped -> arrived.
        # The mock advances it purely by the elapsed time vs. the promised
        # delivery window so order tracking and the customer "your order
        # arrived" notification work against a live demo.
        if elapsed >= window:
            return "arrived"
        if elapsed >= window * 0.7:
            return "shipped"
        if elapsed >= window * 0.3:
            return "assembling"
        return state["status"]

    @staticmethod
    def _matches(query_article: str, catalog_article: str) -> bool:
        return query_article in catalog_article or catalog_article in query_article
