from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import settings
from app.models import (
    Company,
    Conversation,
    PartRequest,
    Quote,
    SupplierOffer,
)
from app.models.shadow_comparison import (
    SHADOW_STATUS_COMPLETED,
    SHADOW_STATUS_PENDING,
    ShadowComparison,
)


def _norm(value: str | None) -> str:
    return " ".join((value or "").split()).casefold()


def _match(ai_value: str, manager_value: str) -> bool | None:
    """Compare two free-text fields. None when either side is empty/unknown."""
    ai = _norm(ai_value)
    manager = _norm(manager_value)
    if not ai or not manager:
        return None
    if ai == manager:
        return True
    if len(ai) >= 3 and ai in manager:
        return True
    return bool(len(manager) >= 3 and manager in ai)


class ShadowService:
    """Shadow Mode (sprint 3.8.1): Agentos and a human manager work the same
    request in parallel; their selections are compared after the fact while
    the customer only ever sees the manager's answer."""

    def __init__(self, db) -> None:
        self.db = db

    # --- Creation -----------------------------------------------------------

    def ensure_for_part_request(self, part_request: PartRequest) -> ShadowComparison | None:
        """Open a pending shadow comparison for a new request, if the company
        runs shadow mode and the pilot limit has not been reached."""
        company = self.db.get(Company, part_request.company_id)
        if company is None or not company.shadow_mode:
            return None
        existing = self.get_for_part_request(part_request.id)
        if existing is not None:
            return existing
        total = int(
            self.db.scalar(
                select(func.count())
                .select_from(ShadowComparison)
                .where(ShadowComparison.company_id == part_request.company_id)
            )
            or 0
        )
        if total >= settings.shadow_mode_limit:
            return None
        comparison = ShadowComparison(
            company_id=part_request.company_id,
            part_request_id=part_request.id,
            conversation_id=part_request.conversation_id,
            customer_id=part_request.customer_id,
            status=SHADOW_STATUS_PENDING,
            ai_part=part_request.part_name,
            ai_article=part_request.article,
            ai_vehicle=self._vehicle_label(part_request),
        )
        self.db.add(comparison)
        self.db.flush()  # stamp created_at (server_default) + make idempotency work
        return comparison

    # --- Read ---------------------------------------------------------------

    def get_for_part_request(self, part_request_id: uuid.UUID) -> ShadowComparison | None:
        stmt = select(ShadowComparison).where(
            ShadowComparison.part_request_id == part_request_id
        )
        return self.db.scalars(stmt).first()

    def list_for_company(self, company_id: uuid.UUID, limit: int = 50) -> list[ShadowComparison]:
        stmt = (
            select(ShadowComparison)
            .where(ShadowComparison.company_id == company_id)
            .order_by(ShadowComparison.created_at.desc())
            .limit(min(limit, 200))
        )
        return list(self.db.scalars(stmt).unique().all())

    def stats(self, company_id: uuid.UUID) -> dict[str, Any]:
        rows = self.list_for_company(company_id, limit=500)
        completed = [r for r in rows if r.status == SHADOW_STATUS_COMPLETED]
        total = len(rows)
        n = len(completed)
        avg_time = (
            sum(r.time_seconds or 0 for r in completed) / n
            if n
            else None
        )
        return {
            "total": total,
            "completed": n,
            "pending": total - n,
            "limit": settings.shadow_mode_limit,
            "vehicle_match_pct": self._pct([r.vehicle_match for r in completed]),
            "part_match_pct": self._pct([r.part_match for r in completed]),
            "oem_match_pct": self._pct([r.oem_match for r in completed]),
            "avg_time_seconds": avg_time,
        }

    @staticmethod
    def _pct(matches: list[bool | None]) -> float | None:
        known = [m for m in matches if m is not None]
        if not known:
            return None
        return round(100 * sum(1 for m in known if m) / len(known), 1)

    # --- Manager submission -------------------------------------------------

    def submit_manager(
        self,
        part_request: PartRequest,
        *,
        vehicle: str = "",
        part: str = "",
        article: str = "",
        offer_ids: list[str] | None = None,
        price: float | None = None,
        reply: str = "",
    ) -> ShadowComparison:
        comparison = self.ensure_for_part_request(part_request) or self.get_for_part_request(
            part_request.id
        )
        if comparison is None:
            company = self.db.get(Company, part_request.company_id)
            if company is None or not company.shadow_mode:
                raise ValueError(
                    "Shadow mode выключен для компании: заявка не в режиме сравнения."
                )
            comparison = self.ensure_for_part_request(part_request)
            if comparison is None:
                raise ValueError(
                    "Лимит shadow-сравнений исчерпан: включите полную автоматизацию."
                )

        ai_offer_ids, ai_price, ai_answer = self._ai_selection(part_request)

        comparison.ai_offer_ids = [str(o) for o in ai_offer_ids]
        comparison.ai_price = ai_price
        comparison.ai_answer = ai_answer
        comparison.manager_vehicle = _norm(vehicle) if vehicle else ""
        comparison.manager_part = _norm(part) if part else ""
        comparison.manager_article = _norm(article) if article else ""
        comparison.manager_offer_ids = [str(o) for o in (offer_ids or [])]
        comparison.manager_price = price
        comparison.manager_reply = reply or ""

        comparison.vehicle_match = _match(comparison.ai_vehicle, comparison.manager_vehicle)
        comparison.part_match = _match(comparison.ai_part, comparison.manager_part)
        comparison.oem_match = _match(comparison.ai_article, comparison.manager_article)
        comparison.offer_overlap = len(
            set(comparison.ai_offer_ids) & set(comparison.manager_offer_ids)
        )
        if comparison.ai_price is not None and comparison.manager_price is not None:
            comparison.price_delta = comparison.manager_price - comparison.ai_price
        else:
            comparison.price_delta = None
        comparison.time_seconds = (
            datetime.now(UTC) - comparison.created_at.replace(tzinfo=UTC)
        ).total_seconds()
        comparison.status = SHADOW_STATUS_COMPLETED
        comparison.evaluated_at = datetime.now(UTC)
        self.db.flush()

        # Fitment Engine (sprint 4.0): a manager confirming the same part and
        # article is direct evidence — the engine learns from every human
        # agreement instead of treating each request as a fresh unknown.
        if comparison.part_match and part_request.article:
            from app.services.fitment_service import FitmentService

            FitmentService(self.db).record_manager_evidence(
                part_request,
                source="shadow",
                confidence=0.9,
                detail={"comparison_id": str(comparison.id)},
            )
        return comparison

    def add_manager_reply(
        self,
        conversation: Conversation,
        comparison: ShadowComparison,
        *,
        user_id: uuid.UUID | None,
    ) -> None:
        """Store the manager's answer to the customer (shadow mode: the client
        always receives the human answer, never the AI one)."""
        if not comparison.manager_reply:
            return
        from app.services.conversation_service import ConversationService

        ConversationService(self.db).add_message(
            conversation,
            content=comparison.manager_reply,
            sender_type="manager",
            sender_id=user_id,
            structured_data={
                "kind": "shadow",
                "comparison_id": str(comparison.id),
                "part_request_id": str(comparison.part_request_id),
            },
        )
        self.db.flush()

    # --- AI side snapshot ---------------------------------------------------

    def _ai_selection(
        self, part_request: PartRequest
    ) -> tuple[list[str], float | None, str]:
        """The AI's final selection for the request: offers chosen, price and
        the message it would have sent (from the quote when one exists)."""
        quote = self._latest_quote(part_request.id)
        if quote is not None:
            offer_ids = [str(item["offer_id"]) for item in quote.items if item.get("offer_id")]
            price = _to_float(quote.quote_total)
            answer = quote.final_message or quote.manager_edited or quote.ai_draft or ""
            if offer_ids:
                return offer_ids, price, answer
        offers = self._priced_offers(part_request.id)
        offer_ids = [str(o.id) for o in offers]
        price = _to_float(offers[0].customer_price) if offers else None
        return offer_ids, price, ""

    def _latest_quote(self, part_request_id: uuid.UUID) -> Quote | None:
        stmt = (
            select(Quote)
            .where(Quote.part_request_id == part_request_id)
            .order_by(Quote.created_at.desc())
        )
        return self.db.scalars(stmt).first()

    def _priced_offers(self, part_request_id: uuid.UUID) -> list[SupplierOffer]:
        stmt = (
            select(SupplierOffer)
            .where(SupplierOffer.part_request_id == part_request_id)
            .order_by(SupplierOffer.customer_price.asc().nulls_last())
        )
        return list(self.db.scalars(stmt).unique().all())

    @staticmethod
    def _vehicle_label(part_request: PartRequest) -> str:
        vehicle = part_request.vehicle
        if vehicle is None:
            return ""
        parts = []
        if vehicle.brand:
            parts.append(vehicle.brand)
        if vehicle.model:
            parts.append(vehicle.model)
        if vehicle.year:
            parts.append(str(vehicle.year))
        label = " ".join(parts)
        if vehicle.vin:
            label += f" (VIN {vehicle.vin})"
        return label


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
