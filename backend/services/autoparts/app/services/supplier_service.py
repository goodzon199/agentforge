from __future__ import annotations

import re
import time
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Supplier
from app.schemas.supplier import SupplierTestResult
from app.suppliers.base import SupplierAdapter, SupplierSearchQuery
from app.suppliers.registry import supplier_registry

_SLUG_STRIP = re.compile(r"[^a-z0-9-]")

# Sprint 4.2: the supplier rating is computed by the system from observed
# data (see SupplierReliabilityService) — it is never hand-typed anymore.
# A "rating" key in create/update payloads is a legacy seed: we accept it at
# first write (so existing flows/tests keep working) but stamp it as stale so
# the next recompute overrides it.
_RATING_MIN, _RATING_MAX = 0.0, 1.0


def normalize_rating(value: Any) -> float:
    """Coerce a supplier rating onto the fixed 0..1 scale.

    Values already in range pass through unchanged; 10-point legacy values
    (>1) are divided by 10 (9.5 -> 0.95); anything non-numeric becomes 0
    (doubtful — never assume reliability).
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number < _RATING_MIN:
        return _RATING_MIN
    if number > _RATING_MAX:
        # Legacy 10-point scale: 9.5 (out of 10) == 0.95.
        if number <= 10.0:
            return round(number / 10.0, 4)
        return _RATING_MAX
    return round(number, 4)


def _normalize_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    settings = dict(settings or {})
    if settings.get("rating") is not None:
        # Accept a legacy hand-typed rating as a seed, but the source of
        # truth is the live computation — mark it as stale.
        settings["rating"] = normalize_rating(settings["rating"])
        settings["rating_source"] = "stale"
    return settings


def _slugify(name: str, salt: str = "") -> str:
    base = _SLUG_STRIP.sub("-", name.lower().strip()).strip("-")
    if not base:
        base = "supplier"
    if salt:
        base = f"{base}-{salt}"
    return base[:120]


class SupplierService:
    """Owns supplier records and adapter instantiation for a company."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, *, company_id: uuid.UUID | None = None) -> list[Supplier]:
        stmt = select(Supplier).order_by(Supplier.created_at.asc())
        if company_id:
            stmt = stmt.where(Supplier.company_id == company_id)
        return list(self.db.scalars(stmt).unique().all())

    def get(self, supplier_id: uuid.UUID) -> Supplier | None:
        return self.db.get(Supplier, supplier_id)

    def get_active(self, company_id: uuid.UUID) -> list[Supplier]:
        stmt = (
            select(Supplier)
            .where(Supplier.company_id == company_id)
            .where(Supplier.is_active.is_(True))
        )
        return list(self.db.scalars(stmt).unique().all())

    def create(
        self,
        *,
        company_id: uuid.UUID,
        name: str,
        adapter_type: str = "mock",
        is_active: bool = True,
        settings: dict[str, Any] | None = None,
    ) -> Supplier:
        self._ensure_adapter_type(adapter_type)
        supplier = Supplier(
            company_id=company_id,
            name=name,
            slug=self._unique_slug(company_id, name),
            adapter_type=adapter_type,
            is_active=is_active,
            settings=_normalize_settings(settings or {}),
        )
        self.db.add(supplier)
        return supplier

    def update(self, supplier: Supplier, **updates: Any) -> Supplier:
        for key, value in updates.items():
            if key in ("id", "company_id", "slug"):
                continue
            if not hasattr(supplier, key):
                continue
            if key == "adapter_type":
                self._ensure_adapter_type(value)
            if key == "settings":
                value = _normalize_settings(value)
            setattr(supplier, key, value)
        return supplier

    def adapter_for(self, supplier: Supplier) -> SupplierAdapter:
        return supplier_registry.create(
            supplier.adapter_type,
            name=supplier.name,
            settings=supplier.settings or {},
        )

    async def test(self, supplier: Supplier) -> SupplierTestResult:
        """Healthcheck + a probe search against the adapter."""
        adapter = self.adapter_for(supplier)
        started = time.monotonic()
        try:
            healthy = await adapter.healthcheck()
            offers = await adapter.search(SupplierSearchQuery(article="P06089"))
            latency = int((time.monotonic() - started) * 1000)
            if not healthy:
                return SupplierTestResult(
                    ok=False, message="Адаптер недоступен.", latency_ms=latency
                )
            return SupplierTestResult(
                ok=True,
                message="Соединение установлено.",
                latency_ms=latency,
                offers_found=len(offers),
            )
        except Exception as exc:
            latency = int((time.monotonic() - started) * 1000)
            return SupplierTestResult(
                ok=False, message=f"Ошибка адаптера: {exc}", latency_ms=latency
            )

    # --- Internals ---------------------------------------------------------

    def _ensure_adapter_type(self, adapter_type: str) -> None:
        if adapter_type not in supplier_registry.types():
            raise ValueError(f"Неизвестный тип адаптера поставщика: {adapter_type}")

    def _unique_slug(self, company_id: uuid.UUID, name: str) -> str:
        base = _slugify(name)
        slug = base
        counter = 1
        existing = {
            s.slug for s in self.list(company_id=company_id)
        }
        while slug in existing:
            slug = _slugify(name, str(counter))
            counter += 1
        return slug
