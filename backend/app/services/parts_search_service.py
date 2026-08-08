from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    PartRequest,
    Supplier,
    SupplierOffer,
    SupplierSearchAttempt,
    SupplierSearchRun,
    Vehicle,
)
from app.models.enums import (
    PartRequestStatus,
    SupplierAttemptStatus,
    SupplierSearchStatus,
)
from app.suppliers.base import NormalizedSupplierOffer, SupplierSearchQuery
from app.suppliers.errors import SupplierQueryNotSupported
from app.suppliers.normalize import normalize_article
from app.services.supplier_service import SupplierService

_NEXT_ACTION = "pricing_parts"

# Internal marker returned by _call_adapter when a supplier cannot handle the
# query (e.g. Rossko has no article to search by). Such attempts are recorded
# as "skipped" and neither count as success nor as failure.
_SKIPPED_MARKER = object()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PartsSearchService:
    """Runs a parts search across a company's active suppliers.

    Suppliers are queried in parallel (``asyncio.gather``); a failing supplier
    never breaks the others. Offers are deduplicated per supplier+article and
    persisted for the pricing step.
    """

    def __init__(self, db: Session, *, timeout: float | None = None) -> None:
        self.db = db
        from app.core.config import settings

        self.timeout = timeout if timeout is not None else settings.supplier_search_timeout

    # --- Search ------------------------------------------------------------

    def search(
        self,
        part_request: PartRequest,
        *,
        triggered_by: str = "agent",
        task_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        run = SupplierSearchRun(
            part_request_id=part_request.id,
            status=SupplierSearchStatus.running,
            structured_data={"triggered_by": triggered_by, "next_action": _NEXT_ACTION},
        )
        if task_id is not None:
            run.structured_data["task_id"] = str(task_id)
        self.db.add(run)
        part_request.status = PartRequestStatus.searching
        self.db.flush()
        # run.id is assigned by the flush; record the latest run so the
        # pricing step resolves it deterministically.
        run_data = part_request.structured_data.copy()
        run_data["latest_search_run_id"] = str(run.id)
        part_request.structured_data = run_data

        suppliers = self._active_suppliers(part_request.company_id)
        if not suppliers:
            run.status = SupplierSearchStatus.failed
            run.error = "Нет активных поставщиков."
            run.completed_at = _now()
            part_request.status = PartRequestStatus.ready_for_search
            self.db.commit()
            return self._result(part_request, run)

        query = self._build_query(part_request)
        attempts = [
            self._create_attempt(run, supplier) for supplier in suppliers
        ]
        run.started_at = _now()
        self.db.commit()

        results = self._run_adapters(suppliers, attempts, query)

        collected: list[tuple[SupplierSearchAttempt, NormalizedSupplierOffer]] = []
        succeeded = 0
        failed = 0
        for attempt, offers, error, latency in results:
            if error is _SKIPPED_MARKER:
                attempt.status = SupplierAttemptStatus.skipped
                attempt.error = (
                    "Поставщик пропущен: запрос без артикула не поддерживается."
                )
                attempt.completed_at = _now()
                continue
            if error:
                attempt.status = SupplierAttemptStatus.failed
                attempt.error = error[:1000]
                attempt.completed_at = _now()
                failed += 1
                continue
            attempt.status = SupplierAttemptStatus.succeeded
            attempt.offers_found = len(offers)
            attempt.latency_ms = latency
            attempt.completed_at = _now()
            succeeded += 1
            collected.extend((attempt, offer) for offer in offers)

        deduped = self._apply_supplier_policy(
            self._dedupe(collected), part_request.company_id, suppliers
        )
        for attempt, offer in deduped:
            self.db.add(
                SupplierOffer(
                    part_request_id=part_request.id,
                    search_run_id=run.id,
                    supplier_id=attempt.supplier_id,
                    brand=offer.brand,
                    article=offer.article,
                    part_name=offer.part_name,
                    purchase_price=offer.purchase_price,
                    quantity=offer.quantity,
                    delivery_days=offer.delivery_days,
                    is_cross=offer.is_cross,
                )
            )

        run.offers_found = len(deduped)
        run.suppliers_succeeded = succeeded
        run.suppliers_failed = failed
        run.status = (
            SupplierSearchStatus.failed
            if suppliers and failed == len(suppliers)
            else SupplierSearchStatus.completed
        )
        run.completed_at = _now()

        part_request.status = (
            PartRequestStatus.quoted
            if run.offers_found > 0
            else PartRequestStatus.ready_for_search
        )
        self.db.commit()
        return self._result(part_request, run)

    # --- Reads -------------------------------------------------------------

    def mark_stale_runs(self, *, max_seconds: float | None = None) -> int:
        """Watchdog: fail search runs stuck in ``running`` (dead worker).

        Mirrors the supplier-timeout safety net at the run level so a search
        can never hang forever. Returns how many runs were marked failed.
        """
        from app.core.config import settings

        limit = (
            max_seconds
            if max_seconds is not None
            else settings.search_run_max_running_seconds
        )
        threshold = _now() - timedelta(seconds=limit)

        stmt = (
            select(SupplierSearchRun)
            .where(SupplierSearchRun.status == SupplierSearchStatus.running)
            .where(SupplierSearchRun.started_at.isnot(None))
            .where(SupplierSearchRun.started_at < threshold)
        )
        runs = list(self.db.scalars(stmt).unique().all())
        for run in runs:
            run.status = SupplierSearchStatus.failed
            run.error = "supplier_failed: превышен лимит времени на поиск"
            run.completed_at = _now()
            part_request = self.db.get(PartRequest, run.part_request_id)
            if part_request is not None and part_request.status == PartRequestStatus.searching:
                part_request.status = PartRequestStatus.ready_for_search
        if runs:
            self.db.commit()
        return len(runs)

    def list_offers(self, part_request_id: uuid.UUID) -> list[SupplierOffer]:
        stmt = (
            select(SupplierOffer)
            .where(SupplierOffer.part_request_id == part_request_id)
            .order_by(
                SupplierOffer.purchase_price.asc().nulls_last(),
                SupplierOffer.created_at.asc(),
            )
        )
        return list(self.db.scalars(stmt).unique().all())

    def list_runs(self, part_request_id: uuid.UUID) -> list[SupplierSearchRun]:
        stmt = (
            select(SupplierSearchRun)
            .where(SupplierSearchRun.part_request_id == part_request_id)
            .order_by(SupplierSearchRun.created_at.desc())
        )
        return list(self.db.scalars(stmt).unique().all())

    def get_run(self, run_id: uuid.UUID) -> SupplierSearchRun | None:
        return self.db.get(SupplierSearchRun, run_id)

    # --- Internals ---------------------------------------------------------

    def _active_suppliers(self, company_id: uuid.UUID) -> list[Supplier]:
        return SupplierService(self.db).get_active(company_id)

    def _create_attempt(
        self, run: SupplierSearchRun, supplier: Supplier
    ) -> SupplierSearchAttempt:
        attempt = SupplierSearchAttempt(
            search_run_id=run.id,
            supplier_id=supplier.id,
            status=SupplierAttemptStatus.pending,
        )
        self.db.add(attempt)
        return attempt

    def _build_query(self, part_request: PartRequest) -> SupplierSearchQuery:
        vehicle: Vehicle | None = None
        if part_request.vehicle_id is not None:
            vehicle = self.db.get(Vehicle, part_request.vehicle_id)
        return SupplierSearchQuery(
            article=part_request.article,
            part_name=part_request.part_name,
            quantity=part_request.quantity,
            vehicle_brand=vehicle.brand if vehicle else "",
            vehicle_model=vehicle.model if vehicle else "",
            vehicle_year=vehicle.year if vehicle else None,
        )

    def _run_adapters(
        self,
        suppliers: list[Supplier],
        attempts: list[SupplierSearchAttempt],
        query: SupplierSearchQuery,
    ) -> list[tuple[SupplierSearchAttempt, list[NormalizedSupplierOffer], Any, int]]:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._gather(suppliers, attempts, query)
            )
        finally:
            loop.close()

    async def _gather(
        self,
        suppliers: list[Supplier],
        attempts: list[SupplierSearchAttempt],
        query: SupplierSearchQuery,
    ) -> list[tuple[SupplierSearchAttempt, list[NormalizedSupplierOffer], Any, int]]:
        tasks = [
            self._call_adapter(supplier, attempt, query)
            for supplier, attempt in zip(suppliers, attempts)
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _call_adapter(
        self,
        supplier: Supplier,
        attempt: SupplierSearchAttempt,
        query: SupplierSearchQuery,
    ) -> tuple[SupplierSearchAttempt, list[NormalizedSupplierOffer], Any, int]:
        started = time.monotonic()
        try:
            adapter = SupplierService(self.db).adapter_for(supplier)
            offers = await asyncio.wait_for(adapter.search(query), timeout=self.timeout)
            latency = int((time.monotonic() - started) * 1000)
            return attempt, offers, None, latency
        except SupplierQueryNotSupported:
            latency = int((time.monotonic() - started) * 1000)
            return attempt, [], _SKIPPED_MARKER, latency
        except Exception as exc:  # noqa: BLE001 - one supplier must not break the run
            latency = int((time.monotonic() - started) * 1000)
            return attempt, [], str(exc)[:1000], latency

    @staticmethod
    def _dedupe(
        collected: list[tuple[SupplierSearchAttempt, NormalizedSupplierOffer]],
    ) -> list[tuple[SupplierSearchAttempt, NormalizedSupplierOffer]]:
        """Keep the cheapest offer per (supplier, normalized article)."""
        best: dict[tuple[str, str], tuple[SupplierSearchAttempt, NormalizedSupplierOffer]] = {}
        for attempt, offer in collected:
            key = (str(attempt.supplier_id), normalize_article(offer.article))
            current = best.get(key)
            if current is None:
                best[key] = (attempt, offer)
                continue
            _, current_offer = current
            if offer.purchase_price is None and current_offer.purchase_price is not None:
                continue
            if current_offer.purchase_price is None or (
                offer.purchase_price is not None
                and offer.purchase_price < current_offer.purchase_price
            ):
                best[key] = (attempt, offer)
        result = list(best.values())
        result.sort(
            key=lambda item: (
                item[1].purchase_price is None,
                item[1].purchase_price or Decimal("0"),
            )
        )
        return result

    def _apply_supplier_policy(
        self,
        collected: list[tuple[SupplierSearchAttempt, NormalizedSupplierOffer]],
        company_id: uuid.UUID,
        suppliers: list[Supplier],
    ) -> list[tuple[SupplierSearchAttempt, NormalizedSupplierOffer]]:
        """Filter/order/limit offers by the company's supplier policy.

        Blocked brands and over-long lead times are dropped, suppliers with
        too low a rating are excluded, favorites and the configured priority
        order win, and the list is trimmed to ``max_variants``.
        """
        from app.services.company_policy_service import CompanyPolicyService

        policy = CompanyPolicyService(self.db).policy(company_id, "supplier")
        blocked = {self._brand(b) for b in (policy.get("blocked_brands") or [])}
        favorite = {self._brand(b) for b in (policy.get("favorite_brands") or [])}
        priority = policy.get("priority") or []
        max_lead = policy.get("max_lead_days")
        min_rating = Decimal(str(policy.get("min_rating") or 0))
        max_variants = policy.get("max_variants")

        slugs = {s.id: s.slug for s in suppliers}
        ratings = {
            s.id: (s.settings or {}).get("rating") for s in suppliers
        }

        ranked: list[tuple[int, int, SupplierSearchAttempt, NormalizedSupplierOffer]] = []
        for attempt, offer in collected:
            slug = slugs.get(attempt.supplier_id, "")
            if self._brand(offer.brand) in blocked:
                continue
            if (
                max_lead is not None
                and offer.delivery_days is not None
                and offer.delivery_days > int(max_lead)
            ):
                continue
            rating = ratings.get(attempt.supplier_id)
            if (
                rating is not None
                and min_rating > 0
                and Decimal(str(rating)) < min_rating
            ):
                continue
            try:
                pidx = priority.index(slug)
            except ValueError:
                pidx = len(priority) + 1
            is_fav = 0 if (slug in favorite or self._brand(offer.brand) in favorite) else 1
            ranked.append((pidx, is_fav, attempt, offer))

        ranked.sort(
            key=lambda r: (
                r[0],
                r[1],
                r[3].purchase_price is None,
                r[3].purchase_price or Decimal("0"),
            )
        )
        result = [(r[2], r[3]) for r in ranked]
        if max_variants:
            result = result[: int(max_variants)]
        return result

    @staticmethod
    def _brand(brand: str) -> str:
        return (brand or "").strip().lower()

    @staticmethod
    def _result(part_request: PartRequest, run: SupplierSearchRun) -> dict[str, Any]:
        return {
            "run_id": run.id,
            "part_request_id": part_request.id,
            "status": run.status.value,
            "offers_found": run.offers_found,
            "suppliers_succeeded": run.suppliers_succeeded,
            "suppliers_failed": run.suppliers_failed,
            "next_action": _NEXT_ACTION,
        }
