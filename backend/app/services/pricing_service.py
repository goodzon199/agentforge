from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, PartRequest, SupplierOffer, SupplierSearchRun

_PRICING_KEY = "pricing"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PricingService:
    """Computes customer-facing prices from supplier offers.

    Rule: customer unit price = purchase price * (1 + margin/100), rounded to
    2 decimals; total = unit * quantity. The margin comes from the company's
    pricing settings (``settings["pricing"]["margin_percent"]``) or the global
    default (``settings.pricing_margin_percent``).

    The result is stamped on each offer (``customer_price`` / ``total_price`` /
    ``margin_percent``) and summarized on the part request under
    ``structured_data["pricing"]`` — source of truth lives in the DB, never
    only in agent memory.
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        from app.core.config import settings

        self.default_margin = Decimal(str(settings.pricing_margin_percent))
        self.currency = settings.pricing_currency

    # --- Public ------------------------------------------------------------

    def process(
        self,
        part_request_id: uuid.UUID,
        run_id: uuid.UUID | None = None,
        *,
        triggered_by: str = "agent",
    ) -> dict[str, Any]:
        """Price the offers of a search run and persist the result."""
        part_request = self.db.get(PartRequest, part_request_id)
        if part_request is None:
            raise ValueError(f"Заявка {part_request_id} не найдена.")

        run = self._resolve_run(part_request, run_id)
        if run is None:
            return self._summary(part_request, run=None, offers=[], priced=[])

        margin = self._margin_for(part_request.company_id)
        offers = self._offers_for_run(run.id)

        priced: list[tuple[SupplierOffer, Decimal, Decimal]] = []
        for offer in offers:
            if offer.purchase_price is None:
                continue
            unit = self.price(offer.purchase_price, margin)
            qty = part_request.quantity or 1
            total = (unit * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            offer.customer_price = unit
            offer.total_price = total
            offer.margin_percent = margin
            priced.append((offer, unit, total))

        best = self._best(priced)
        summary = self._summary(
            part_request,
            run=run,
            offers=offers,
            priced=priced,
            best=best,
            margin=margin,
            triggered_by=triggered_by,
        )

        quote = None
        if priced:
            from app.services.quote_service import QuoteService

            quote = QuoteService(self.db).ensure_from_pricing(
                part_request,
                offers=offers,
                best=best,
                margin=margin,
                currency=self.currency,
            )
            if quote is not None:
                summary["quote_id"] = str(quote.id)

        data = (
            part_request.structured_data.copy()
            if isinstance(part_request.structured_data, dict)
            else {}
        )
        data[_PRICING_KEY] = summary
        part_request.structured_data = data
        self.db.commit()

        if quote is not None:
            # Automatic hand-off: after pricing the platform prepares a sales
            # draft (SalesAgent) so a manager can review and send it.
            from app.services.quote_service import QuoteService

            QuoteService(self.db).submit_sales_draft(quote, part_request)

        return summary

    def summary(self, part_request_id: uuid.UUID) -> dict[str, Any] | None:
        """Read the stored quote (no side effects) for GET /quote."""
        part_request = self.db.get(PartRequest, part_request_id)
        if part_request is None:
            return None
        stored = part_request.structured_data.get(_PRICING_KEY)
        if stored is not None:
            return stored
        run = self._resolve_run(part_request, None)
        result = self._summary(part_request, run=run, offers=[], priced=[])
        result["status"] = "not_priced"
        return result

    @staticmethod
    def price(purchase_price: Decimal, margin_percent: Decimal) -> Decimal:
        """Unit price = purchase price * (1 + margin/100), rounded half-up."""
        unit = (
            Decimal(str(purchase_price))
            * (Decimal("1") + Decimal(str(margin_percent)) / Decimal("100"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return unit

    # --- Internals ---------------------------------------------------------

    def _margin_for(self, company_id: uuid.UUID) -> Decimal:
        company = self.db.get(Company, company_id)
        settings = (company.settings or {}) if company else {}
        pricing = settings.get("pricing") or {}
        return Decimal(str(pricing.get("margin_percent", self.default_margin)))

    def _resolve_run(
        self, part_request: PartRequest, run_id: uuid.UUID | None
    ) -> SupplierSearchRun | None:
        if run_id is not None:
            return self.db.get(SupplierSearchRun, run_id)
        # The search service records the most recent run on the request, so
        # "latest" is deterministic even when created_at ties.
        stored = part_request.structured_data.get("latest_search_run_id")
        if stored:
            try:
                run = self.db.get(SupplierSearchRun, uuid.UUID(str(stored)))
            except (ValueError, TypeError):
                run = None
            if run is not None:
                return run
        stmt = (
            select(SupplierSearchRun)
            .where(SupplierSearchRun.part_request_id == part_request.id)
            .order_by(
                SupplierSearchRun.created_at.desc(),
                SupplierSearchRun.id.desc(),
            )
        )
        return self.db.scalars(stmt).first()

    def _offers_for_run(self, run_id: uuid.UUID) -> list[SupplierOffer]:
        stmt = (
            select(SupplierOffer)
            .where(SupplierOffer.search_run_id == run_id)
            .order_by(SupplierOffer.created_at.asc())
        )
        return list(self.db.scalars(stmt).unique().all())

    @staticmethod
    def _best(
        priced: list[tuple[SupplierOffer, Decimal, Decimal]]
    ) -> SupplierOffer | None:
        if not priced:
            return None
        return min(priced, key=lambda item: (item[2], item[1]))[0]

    def _summary(
        self,
        part_request: PartRequest,
        *,
        run: SupplierSearchRun | None,
        offers: list[SupplierOffer],
        priced: list[tuple[SupplierOffer, Decimal, Decimal]],
        best: SupplierOffer | None = None,
        margin: Decimal | None = None,
        triggered_by: str = "",
    ) -> dict[str, Any]:
        status = "no_run" if run is None else ("priced" if priced else "no_offers")
        return {
            "status": status,
            "part_request_id": str(part_request.id),
            "run_id": str(run.id) if run is not None else None,
            "triggered_by": triggered_by,
            "margin_percent": float(margin) if margin is not None else None,
            "currency": self.currency,
            "offers_total": len(offers),
            "offers_priced": len(priced),
            "quantity": part_request.quantity,
            "best_offer_id": str(best.id) if best is not None else None,
            "best_brand": best.brand if best is not None else "",
            "best_article": best.article if best is not None else "",
            "best_part_name": best.part_name if best is not None else "",
            "best_unit_price": str(best.customer_price) if best is not None else None,
            "best_total_price": str(best.total_price) if best is not None else None,
            "priced_at": _now().isoformat() if priced else None,
        }
