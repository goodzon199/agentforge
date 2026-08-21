from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import PartRequest, Supplier, SupplierOffer

# Sprint 4.3: composite offer ranking. Five signals blended into one 0..1 score:
#   price          — cheaper beats pricier within the same run;
#   delivery       — faster beats slower (unknown days are neutral);
#   supplier       — the sprint-4.2 auto rating (unknown = neutral 0.5);
#   fitment        — direct offers beat cross references;
#   availability   — enough stock to cover the requested quantity.
# Price keeps the biggest vote, but a slow / unreliable / cross offer can no
# longer win on price alone.
_WEIGHTS = {
    "price": 0.35,
    "delivery": 0.20,
    "supplier": 0.25,
    "fitment": 0.10,
    "availability": 0.10,
}
_NEUTRAL_SUPPLIER = 0.5
_FITMENT_DIRECT = 0.9
_FITMENT_CROSS = 0.5


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _supplier_rating(supplier: Supplier | None) -> float:
    if supplier is None:
        return _NEUTRAL_SUPPLIER
    rating = _to_float((supplier.settings or {}).get("rating"))
    return rating if rating is not None else _NEUTRAL_SUPPLIER


def _reasons(
    *,
    price: str | None,
    delivery: str | None,
    supplier: str | None,
    fitment: str | None,
    availability: str | None,
) -> list[str]:
    return [r for r in (price, delivery, supplier, fitment, availability) if r]


class OfferRankingService:
    """Ranks priced offers of a part request and stamps rank/score/reasons."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Public API ----------------------------------------------------------

    def rank(self, part_request: PartRequest, priced: list[SupplierOffer]) -> list[SupplierOffer]:
        """Assign rank 1..n to every priced offer (best = first). Persists."""
        if not priced:
            return []

        totals = [_to_float(o.total_price) for o in priced]
        days = [_to_float(o.delivery_days) for o in priced]
        min_total = min((v for v in totals if v is not None), default=0.0)
        max_total = max((v for v in totals if v is not None), default=0.0)
        min_days = min((v for v in days if v is not None), default=0.0)
        max_days = max((v for v in days if v is not None), default=0.0)
        requested = part_request.quantity or 1

        scored: list[tuple[SupplierOffer, float]] = []
        for offer in priced:
            score, reasons = self._score(
                offer,
                total=float(offer.total_price or 0),
                min_total=min_total,
                max_total=max_total,
                days=float(offer.delivery_days or 0),
                min_days=min_days,
                max_days=max_days,
                requested=requested,
            )
            offer.rank_score = Decimal(str(round(score, 4)))
            offer.rank_reasons = reasons
            scored.append((offer, score))

        scored.sort(key=lambda item: (-item[1], item[0].created_at))
        for position, (offer, _score) in enumerate(scored, start=1):
            offer.rank = position
        return [offer for offer, _score in scored]

    # --- Scoring -------------------------------------------------------------

    def _score(
        self,
        offer: SupplierOffer,
        *,
        total: float,
        min_total: float,
        max_total: float,
        days: float,
        min_days: float,
        max_days: float,
        requested: int,
    ) -> tuple[float, list[str]]:
        price_score = self._price_score(total, min_total, max_total)
        delivery_score = self._delivery_score(days, min_days, max_days)
        supplier_rating = _supplier_rating(offer.supplier)
        fitment_score = _FITMENT_DIRECT if not offer.is_cross else _FITMENT_CROSS
        availability_score = self._availability_score(offer.quantity, requested)

        reasons = _reasons(
            price=self._price_reason(total, min_total, max_total, price_score),
            delivery=self._delivery_reason(days, min_days, max_days, delivery_score),
            supplier=self._supplier_reason(supplier_rating),
            fitment=self._fitment_reason(offer),
            availability=self._availability_reason(offer.quantity, requested),
        )

        score = (
            _WEIGHTS["price"] * price_score
            + _WEIGHTS["delivery"] * delivery_score
            + _WEIGHTS["supplier"] * supplier_rating
            + _WEIGHTS["fitment"] * fitment_score
            + _WEIGHTS["availability"] * availability_score
        )
        return score, reasons

    @staticmethod
    def _price_score(total: float, min_total: float, max_total: float) -> float:
        if max_total <= min_total:
            return 1.0
        return max(0.0, 1.0 - (total - min_total) / (max_total - min_total))

    @staticmethod
    def _delivery_score(days: float, min_days: float, max_days: float) -> float:
        if max_days <= min_days:
            return 0.5 if max_days == 0 else 1.0
        return max(0.0, 1.0 - (days - min_days) / (max_days - min_days))

    @staticmethod
    def _availability_score(quantity: int | None, requested: int) -> float:
        if quantity is None:
            return 0.5
        if quantity >= requested:
            return 1.0
        return max(0.0, quantity / requested)

    # --- Reasons -------------------------------------------------------------

    @staticmethod
    def _price_reason(total: float, min_total: float, max_total: float, score: float) -> str | None:
        if max_total <= min_total:
            return None
        return None if score >= 1.0 else f"дорожнее минимума на {total - min_total:.2f}"

    @staticmethod
    def _delivery_reason(days: float, min_days: float, max_days: float, score: float) -> str | None:
        if max_days <= min_days or max_days == 0:
            return None
        if score >= 1.0:
            return "самый короткий срок"
        if score <= 0.0:
            return "самый долгий срок"
        return "дольше самого короткого срока"

    @staticmethod
    def _supplier_reason(rating: float) -> str | None:
        if rating >= 0.8:
            return "надёжный поставщик"
        if rating <= 0.3:
            return "низкий рейтинг поставщика"
        if rating != _NEUTRAL_SUPPLIER:
            return "средний рейтинг поставщика"
        return None

    @staticmethod
    def _fitment_reason(offer: SupplierOffer) -> str | None:
        return "кросс-замена" if offer.is_cross else "прямой артикул"

    @staticmethod
    def _availability_reason(quantity: int | None, requested: int) -> str | None:
        if quantity is None:
            return None
        if quantity < requested:
            return f"на складе меньше {requested} шт"
        return None
