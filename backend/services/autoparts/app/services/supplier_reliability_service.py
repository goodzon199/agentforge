from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Order,
    PartReturn,
    Supplier,
    SupplierFulfillment,
    SupplierOffer,
    SupplierSearchAttempt,
)
from app.models.enums import OrderStatus, SupplierAttemptStatus

# How the 0..1 supplier rating is built. Two components blended into one score:
#  - reliability: order/fulfillment/return behaviour of the supplier;
#  - api_availability: whether the adapter actually answers when called.
# The blend gives operations the dominant vote but never lets a fast-but-empty
# API masquerade as a good supplier.
_RATING_VERSION = "4.2.0"
_RELIABILITY_WEIGHT = 0.85
_API_WEIGHT = 0.15

# A supplier with no observed history yet gets a neutral prior (0.5), never a
# blank — auto-send still demands >= 0.8, so unknown suppliers stay in the
# manager loop until they earn a track record.
_NEUTRAL_PRIOR = 0.5

# An empty answer below this latency pool size is statistically meaningless.
_MIN_SAMPLE = 3


@dataclass
class SupplierReliability:
    """The full scoreboard behind one supplier (sprint 4.2)."""

    supplier_id: str
    supplier_name: str
    rating: float  # 0..1 composite, written to settings["rating"]
    rating_source: str  # "auto" — never hand-typed anymore
    rating_version: str
    computed_at: str

    # Order-level metrics (from orders attributed via offer_id).
    orders_total: int
    confirmed: int
    cancelled: int
    confirmation_rate: float | None  # %
    cancellation_rate: float | None  # %

    # Fulfillment-level metrics (promised vs actual).
    fulfillments_total: int
    fulfillments_recorded: int  # with at least one actual recorded
    on_time_delivery: float | None  # %
    price_change_rate: float | None  # %
    under_delivery_rate: float | None  # %

    # Returns (part_returns.supplier_id).
    returns_total: int
    return_rate: float | None  # % of orders returned

    # API behaviour (supplier_search_attempts).
    attempts_total: int
    attempts_failed: int
    api_availability: float | None  # %
    api_avg_latency_ms: float | None
    api_p95_latency_ms: float | None

    # The composite parts (0..1, as blended).
    reliability_score: float
    api_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SupplierReliabilityService:
    """Computes the 8 supplier-intelligence metrics and the composite rating.

    The rating is *always* computed from observed data and stored in
    ``supplier.settings["rating"]``; a hand-typed value in create/update is
    treated as a legacy seed and is overwritten by the first recompute.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Public API ----------------------------------------------------------

    def compute(self, supplier: Supplier) -> SupplierReliability:
        """Recompute the scoreboard for a supplier (does not persist)."""
        metrics = self._collect(supplier)
        reliability = self._reliability_score(metrics)
        api_score = self._api_score(metrics)
        rating = round(
            _RELIABILITY_WEIGHT * reliability + _API_WEIGHT * api_score, 4
        )
        return SupplierReliability(
            supplier_id=str(supplier.id),
            supplier_name=supplier.name,
            rating=rating,
            rating_source="auto",
            rating_version=_RATING_VERSION,
            computed_at=datetime.now(UTC).isoformat(),
            orders_total=metrics["orders_total"],
            confirmed=metrics["confirmed"],
            cancelled=metrics["cancelled"],
            confirmation_rate=metrics["confirmation_rate"],
            cancellation_rate=metrics["cancellation_rate"],
            fulfillments_total=metrics["fulfillments_total"],
            fulfillments_recorded=metrics["fulfillments_recorded"],
            on_time_delivery=metrics["on_time_delivery"],
            price_change_rate=metrics["price_change_rate"],
            under_delivery_rate=metrics["under_delivery_rate"],
            returns_total=metrics["returns_total"],
            return_rate=metrics["return_rate"],
            attempts_total=metrics["attempts_total"],
            attempts_failed=metrics["attempts_failed"],
            api_availability=metrics["api_availability"],
            api_avg_latency_ms=metrics["api_avg_latency_ms"],
            api_p95_latency_ms=metrics["api_p95_latency_ms"],
            reliability_score=round(reliability, 4),
            api_score=round(api_score, 4),
        )

    def refresh(self, supplier: Supplier) -> SupplierReliability:
        """Recompute and persist the rating into ``settings["rating"]``."""
        result = self.compute(supplier)
        settings = dict(supplier.settings or {})
        settings["rating"] = result.rating
        settings["rating_source"] = "auto"
        settings["rating_version"] = _RATING_VERSION
        supplier.settings = settings
        self.db.flush()
        return result

    def recompute_all(self, company_id: uuid.UUID) -> list[SupplierReliability]:
        """Recompute the rating of every supplier of a company."""
        suppliers = list(
            self.db.scalars(
                select(Supplier).where(Supplier.company_id == company_id)
            ).unique()
        )
        results = [self.refresh(s) for s in suppliers]
        self.db.commit()
        return results

    def record_fulfillments_for_order(self, order: Order) -> None:
        """Snapshot the *promised* reality of every order line.

        Called from OrderService.create_from_quote: each line of the order
        gets a SupplierFulfillment row carrying what the supplier promised
        (purchase price, delivery days, quantity). The manager later records
        what actually happened; the difference becomes the metrics.
        """
        offers = self._offers_for_order(order)
        for item in order.items or []:
            offer = offers.get(str(item.get("offer_id")))
            if offer is None or offer.supplier_id is None:
                continue
            self.db.add(
                SupplierFulfillment(
                    company_id=order.company_id,
                    supplier_id=offer.supplier_id,
                    order_id=order.id,
                    offer_id=offer.id,
                    article=str(item.get("article") or "").strip(),
                    brand=str(item.get("brand") or "").strip(),
                    promised_purchase_price=offer.purchase_price,
                    promised_delivery_days=offer.delivery_days
                    if offer.delivery_days is not None
                    else _item_int(item, "delivery_days"),
                    quantity_ordered=_item_int(item, "quantity_available")
                    or _item_int(item, "quantity"),
                    status="delivered",
                )
            )
            supplier = self.db.get(Supplier, offer.supplier_id)
            if supplier is not None:
                self.refresh(supplier)
        self.db.flush()

    def record_fulfillment_actual(
        self,
        supplier: Supplier,
        *,
        fulfillment_id: uuid.UUID | None = None,
        order_id: uuid.UUID | None = None,
        article: str | None = None,
        actual_purchase_price: Decimal | None = None,
        actual_delivery_days: int | None = None,
        quantity_delivered: int | None = None,
        status: str = "delivered",
        delivered_at: datetime | None = None,
    ) -> SupplierFulfillment | None:
        """Manager records what actually happened on a fulfillment line."""
        fulfillment = None
        if fulfillment_id is not None:
            fulfillment = self.db.get(SupplierFulfillment, fulfillment_id)
        if fulfillment is None and order_id is not None and article:
            fulfillment = self.db.scalars(
                select(SupplierFulfillment)
                .where(
                    SupplierFulfillment.supplier_id == supplier.id,
                    SupplierFulfillment.order_id == order_id,
                    SupplierFulfillment.article == article.strip(),
                )
                .order_by(SupplierFulfillment.created_at.desc())
            ).first()
        if fulfillment is None:
            return None
        if actual_purchase_price is not None:
            fulfillment.actual_purchase_price = actual_purchase_price
        if actual_delivery_days is not None:
            fulfillment.actual_delivery_days = actual_delivery_days
        if quantity_delivered is not None:
            fulfillment.quantity_delivered = quantity_delivered
        if status in ("delivered", "partial", "cancelled", "returned"):
            fulfillment.status = status
        if delivered_at is not None:
            fulfillment.delivered_at = delivered_at
        self.refresh(supplier)
        self.db.flush()
        return fulfillment

    # --- Metric collection ---------------------------------------------------

    def _collect(self, supplier: Supplier) -> dict[str, Any]:
        orders, confirmed, cancelled = self._order_stats(supplier)
        orders_total = len(orders)
        confirmation_rate = (
            round(confirmed / orders_total * 100, 1) if orders_total else None
        )
        cancellation_rate = (
            round(cancelled / orders_total * 100, 1) if orders_total else None
        )

        fulfillments = self._fulfillments(supplier)
        on_time = self._on_time_delivery(fulfillments)
        price_change = self._price_change_rate(fulfillments)
        under_delivery = self._under_delivery_rate(fulfillments)

        returns_total = self._returns_total(supplier)
        return_rate = (
            round(returns_total / orders_total * 100, 1)
            if orders_total
            else None
        )

        attempts = self._attempts(supplier)
        attempts_total = len(attempts)
        failed = sum(1 for a in attempts if a.status == SupplierAttemptStatus.failed)
        api_availability = (
            round((attempts_total - failed) / attempts_total * 100, 1)
            if attempts_total
            else None
        )
        latencies = sorted(
            a.latency_ms for a in attempts if a.latency_ms is not None
        )
        api_avg = round(sum(latencies) / len(latencies), 1) if latencies else None
        api_p95 = _percentile(latencies, 0.95)

        return {
            "orders_total": orders_total,
            "confirmed": confirmed,
            "cancelled": cancelled,
            "confirmation_rate": confirmation_rate,
            "cancellation_rate": cancellation_rate,
            "fulfillments_total": len(fulfillments),
            "fulfillments_recorded": self._recorded_count(fulfillments),
            "on_time_delivery": on_time,
            "price_change_rate": price_change,
            "under_delivery_rate": under_delivery,
            "returns_total": returns_total,
            "return_rate": return_rate,
            "attempts_total": attempts_total,
            "attempts_failed": failed,
            "api_availability": api_availability,
            "api_avg_latency_ms": api_avg,
            "api_p95_latency_ms": api_p95,
        }

    def _order_stats(self, supplier: Supplier) -> tuple[list[Order], int, int]:
        """Orders attributed to a supplier via the offer_id in their items."""
        offer_ids = list(
            self.db.scalars(
                select(SupplierOffer.id).where(
                    SupplierOffer.supplier_id == supplier.id
                )
            ).all()
        )
        offer_id_set = {str(o) for o in offer_ids}
        if not offer_id_set:
            return [], 0, 0
        orders = list(
            self.db.scalars(
                select(Order).where(Order.company_id == supplier.company_id)
            ).unique()
        )
        matched: list[Order] = []
        for order in orders:
            if any(
                str(item.get("offer_id")) in offer_id_set
                for item in (order.items or [])
                if item.get("offer_id")
            ):
                matched.append(order)
        confirmed = sum(
            1
            for o in matched
            if o.status in (OrderStatus.confirmed, OrderStatus.paid)
        )
        cancelled = sum(1 for o in matched if o.status == OrderStatus.cancelled)
        return matched, confirmed, cancelled

    def _fulfillments(self, supplier: Supplier) -> list[SupplierFulfillment]:
        return list(
            self.db.scalars(
                select(SupplierFulfillment).where(
                    SupplierFulfillment.supplier_id == supplier.id
                )
            ).unique()
        )

    @staticmethod
    def _recorded_count(fulfillments: list[SupplierFulfillment]) -> int:
        return sum(
            1
            for f in fulfillments
            if f.actual_purchase_price is not None
            or f.actual_delivery_days is not None
            or f.quantity_delivered is not None
        )

    @staticmethod
    def _on_time_delivery(
        fulfillments: list[SupplierFulfillment],
    ) -> float | None:
        """% of delivered lines whose actual_delivery_days <= promised."""
        recorded = [
            f
            for f in fulfillments
            if f.actual_delivery_days is not None
            and f.promised_delivery_days is not None
        ]
        if not recorded:
            return None
        on_time = sum(
            1 for f in recorded if f.actual_delivery_days <= f.promised_delivery_days
        )
        return round(on_time / len(recorded) * 100, 1)

    @staticmethod
    def _price_change_rate(
        fulfillments: list[SupplierFulfillment],
    ) -> float | None:
        """% of recorded lines whose actual price differs from promised."""
        recorded = [
            f
            for f in fulfillments
            if f.actual_purchase_price is not None
            and f.promised_purchase_price is not None
        ]
        if not recorded:
            return None
        changed = sum(
            1
            for f in recorded
            if Decimal(f.actual_purchase_price) != Decimal(f.promised_purchase_price)
        )
        return round(changed / len(recorded) * 100, 1)

    @staticmethod
    def _under_delivery_rate(
        fulfillments: list[SupplierFulfillment],
    ) -> float | None:
        """% of lines delivered with fewer units than ordered."""
        recorded = [
            f
            for f in fulfillments
            if f.quantity_delivered is not None
            and f.quantity_ordered is not None
        ]
        if not recorded:
            return None
        short = sum(
            1 for f in recorded if f.quantity_delivered < f.quantity_ordered
        )
        return round(short / len(recorded) * 100, 1)

    def _returns_total(self, supplier: Supplier) -> int:
        return len(
            list(
                self.db.scalars(
                    select(PartReturn).where(
                        PartReturn.supplier_id == supplier.id
                    )
                ).all()
            )
        )

    def _attempts(self, supplier: Supplier) -> list[SupplierSearchAttempt]:
        return list(
            self.db.scalars(
                select(SupplierSearchAttempt).where(
                    SupplierSearchAttempt.supplier_id == supplier.id
                )
            ).unique()
        )

    def _offers_for_order(self, order: Order) -> dict[str, SupplierOffer]:
        offer_ids = [
            uuid.UUID(str(item["offer_id"]))
            for item in (order.items or [])
            if item.get("offer_id")
        ]
        if not offer_ids:
            return {}
        offers = self.db.scalars(
            select(SupplierOffer).where(SupplierOffer.id.in_(offer_ids))
        ).all()
        return {str(o.id): o for o in offers}

    # --- Scoring -------------------------------------------------------------

    def _reliability_score(self, m: dict[str, Any]) -> float:
        """0..1 weighted blend of the six order/fulfillment/return metrics."""
        parts: list[tuple[float, float]] = []  # (weight, normalized 0..1)
        parts.append((1.0, _pct_score(m["confirmation_rate"])))
        parts.append((1.0, 1 - _pct_score(m["cancellation_rate"])))
        parts.append((1.0, _pct_score(m["on_time_delivery"])))
        parts.append((1.0, 1 - _pct_score(m["price_change_rate"])))
        parts.append((1.0, 1 - _pct_score(m["under_delivery_rate"])))
        parts.append((1.0, 1 - _pct_score(m["return_rate"])))
        weighted = sum(w * s for w, s in parts)
        total = sum(w for w, _ in parts)
        # A completely unknown supplier lands exactly on the neutral prior.
        if total <= 0:
            return _NEUTRAL_PRIOR
        return weighted / total

    def _api_score(self, m: dict[str, Any]) -> float:
        """0..1 blend of API availability and latency speed."""
        if not m["attempts_total"]:
            return _NEUTRAL_PRIOR
        availability = _pct_score(m["api_availability"])
        p95 = m["api_p95_latency_ms"]
        # Speed: p95 == 0ms is perfect (1.0); 4000ms+ is a miss (0.0).
        speed = max(0.0, 1.0 - (p95 or 0) / 4000.0) if p95 is not None else 0.5
        return 0.6 * availability + 0.4 * speed


# --- Pure helpers ---------------------------------------------------------


def _pct_score(value: float | None) -> float:
    """A percentage (0..100) or None -> normalized 0..1; None = neutral."""
    if value is None:
        return _NEUTRAL_PRIOR
    return max(0.0, min(1.0, value / 100.0))


def _percentile(sorted_values: list[int], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) < _MIN_SAMPLE:
        return float(sorted_values[-1])
    idx = (len(sorted_values) - 1) * q
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return float(sorted_values[lower])
    frac = idx - lower
    return float(sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac)


def _item_int(item: dict[str, Any], key: str) -> int | None:
    """Coerce a quote-item JSON field to an int (or None)."""
    value = item.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
