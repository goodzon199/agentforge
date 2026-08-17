from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PartRequest, Quote, SupplierOffer, Task
from app.models.enums import QuoteStatus
from app.services.task_service import TaskService


class QuoteService:
    """Owns the Quote entity: created from a pricing result, drives the
    sales funnel and hands the draft preparation to SalesAgent."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Lookup ------------------------------------------------------------

    def get(self, quote_id: uuid.UUID) -> Quote | None:
        return self.db.get(Quote, quote_id)

    def get_for_part_request(self, part_request_id: uuid.UUID) -> Quote | None:
        stmt = (
            select(Quote)
            .where(Quote.part_request_id == part_request_id)
            .order_by(Quote.created_at.desc(), Quote.id.desc())
        )
        return self.db.scalars(stmt).first()

    # --- Creation / update from a pricing result ---------------------------

    def ensure_from_pricing(
        self,
        part_request: PartRequest,
        *,
        offers: list[SupplierOffer],
        best: SupplierOffer | None,
        margin: Decimal,
        currency: str,
    ) -> Quote | None:
        """Create or refresh the quote from the priced offers of a run.

        Returns None when there is nothing priced. A quote that has already
        progressed past approval is never overwritten by a re-price.
        """
        from app.tracing.tracer import record_span

        quote = self._ensure_from_pricing(
            part_request, offers=offers, best=best, margin=margin, currency=currency
        )
        if quote is not None:
            record_span(
                self.db,
                "quote",
                f"Квота для заявки {part_request.part_name}",
                status="ok",
                duration_ms=0,
                metadata={"quote_id": str(quote.id), "status": quote.status.value},
            )
        return quote

    def _ensure_from_pricing(
        self,
        part_request: PartRequest,
        *,
        offers: list[SupplierOffer],
        best: SupplierOffer | None,
        margin: Decimal,
        currency: str,
    ) -> Quote | None:
        priced = [o for o in offers if o.customer_price is not None]
        if not priced:
            return None

        quote = self.get_for_part_request(part_request.id)
        if quote is not None and quote.status not in (
            QuoteStatus.draft,
            QuoteStatus.pending_approval,
        ):
            return quote

        items = self._items_snapshot(priced)
        total = (
            best.total_price
            if best is not None and best.total_price is not None
            else sum(
                (Decimal(str(it["total_price"])) for it in items if it.get("total_price")),
                Decimal("0"),
            )
        )

        if quote is None:
            quote = Quote(
                company_id=part_request.company_id,
                part_request_id=part_request.id,
                conversation_id=part_request.conversation_id,
                status=QuoteStatus.draft,
                currency=currency,
            )
            self.db.add(quote)
        else:
            # A re-price changes the numbers — the old draft is stale.
            quote.ai_draft = None
            quote.manager_edited = None
            quote.final_message = None
            quote.guard_status = "none"
            quote.guard_errors = None

        quote.best_offer_id = best.id if best is not None else None
        quote.quote_total = total
        quote.items = items
        self.db.flush()
        return quote

    def submit_sales_draft(self, quote: Quote, part_request: PartRequest) -> Task | None:
        """Hand the quote to SalesAgent so a customer-facing draft is prepared."""
        task = TaskService(self.db).create(
            company_id=quote.company_id,
            title=f"Подготовка предложения: {part_request.part_name}",
            objective="sales_draft",
            input_data={
                "quote_id": str(quote.id),
                "part_request_id": str(part_request.id),
                "conversation_id": str(quote.conversation_id),
            },
        )
        self.db.add(task)
        self.db.flush()
        from app.orchestrator.orchestrator import orchestrator  # avoid circular import

        orchestrator.submit(self.db, task)
        return task

    @staticmethod
    def _items_snapshot(priced: list[SupplierOffer]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for offer in priced:
            items.append(
                {
                    "offer_id": str(offer.id),
                    "brand": offer.brand,
                    "article": offer.article,
                    "part_name": offer.part_name,
                    "sale_price": str(offer.customer_price) if offer.customer_price else None,
                    "total_price": str(offer.total_price) if offer.total_price else None,
                    "delivery_days": offer.delivery_days,
                    "quantity_available": offer.quantity,
                    "margin_percent": str(offer.margin_percent) if offer.margin_percent else None,
                }
            )
        return items
