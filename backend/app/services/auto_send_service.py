from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PartRequest, Quote, Supplier, SupplierOffer
from app.services.company_policy_service import CompanyPolicyService

# Supplier ratings are on a fixed 0..1 scale (1.0 = perfect). Any value outside
# the range is treated as doubtful — a 9.5 legacy "10-point" rating must NEVER
# silently pass a 0.8 auto-send threshold.
RATING_MIN, RATING_MAX = Decimal("0"), Decimal("1")


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _rating_in_range(value: Decimal) -> bool:
    return RATING_MIN <= value <= RATING_MAX


class AutoSendService:
    """Sprint 3.8.3 — Controlled Auto (hardened in 3.8.3a).

    Auto-send is only allowed when EVERY safe condition holds; anything
    doubtful goes to the manager for approval:

    1. Policy: auto_send_quote is on AND quote_total within the approval
       auto-approve threshold (AND, not OR — the flag is a global kill-switch).
    2. QuoteGuard passed on the final message (quote.guard_status == "pass").
    3. High intent confidence (the customer clearly wants a part) AND — for a
       VIN-dependent fitment — a real fitment_confidence. intent_confidence is
       NOT a substitute for fitment confidence; without a fitment engine a
       VIN-dependent pick is never auto-sent.
    4. High supplier reliability (every quoted offer's supplier rating on the
       0..1 scale >= threshold; a missing or out-of-range rating is doubtful).
    5. Standard request (no missing fields, part_search intent).

    The decision is deterministic and recorded on the quote for auditing.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def decision(self, quote: Quote) -> dict[str, Any]:
        """Evaluate all safe conditions for one quote.

        Returns ``{auto, reasons, blocks, checks, thresholds}`` where ``reasons``
        explains why it is safe, ``blocks`` lists the conditions that failed
        (empty when ``auto`` is True) and ``thresholds`` snapshots the exact
        policy values used — the audit record.
        """
        checks = {
            "policy": self._policy_ok(quote),
            "guard": self._guard_ok(quote),
            "intent": self._intent_ok(quote),
            "fitment": self._fitment_ok(quote),
            "supplier": self._suppliers_ok(quote),
            "standard": self._standard_ok(quote),
        }
        blocks = [reason for ok, reason in checks.values() if not ok]
        reasons = [reason for ok, reason in checks.values() if ok]
        return {
            "auto": not blocks,
            "reasons": reasons,
            "blocks": blocks,
            "checks": {name: ok for name, (ok, _) in checks.items()},
            "thresholds": self._thresholds(quote.company_id),
            "quote_version": quote.version,
        }

    def snapshot(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Persistable snapshot of a decision (sans transient blocks text)."""
        return {
            "policy": decision["checks"]["policy"],
            "guard": decision["checks"]["guard"],
            "intent": decision["checks"]["intent"],
            "fitment": decision["checks"]["fitment"],
            "supplier": decision["checks"]["supplier"],
            "standard": decision["checks"]["standard"],
            "thresholds": decision.get("thresholds", {}),
            "quote_version": decision.get("quote_version"),
        }

    # --- Individual checks -------------------------------------------------

    def _policy_ok(self, quote: Quote) -> tuple[bool, str]:
        cps = CompanyPolicyService(self.db)
        sales = cps.policy(quote.company_id, "sales")
        if sales.get("auto_send_quote") is not True:
            return False, "auto_send_quote выключен — авто-отправка запрещена"
        approval = cps.policy(quote.company_id, "approval")
        threshold = approval.get("auto_approve_quote_amount")
        if threshold is None:
            return False, "Не задан порог auto_approve_quote_amount — авто-отправка запрещена"
        total = _dec(quote.quote_total)
        allowed = total > 0 and total <= Decimal(str(threshold))
        return (
            allowed,
            f"Сумма {total} в рамках порога авто-одобрения {threshold}"
            if allowed
            else f"Сумма {total} превышает порог авто-одобрения {threshold}",
        )

    def _guard_ok(self, quote: Quote) -> tuple[bool, str]:
        if quote.guard_status == "pass":
            return True, "QuoteGuard прошёл проверку"
        return False, "QuoteGuard не пропустил сообщение"

    def _intent_ok(self, quote: Quote) -> tuple[bool, str]:
        cps = CompanyPolicyService(self.db)
        threshold = _dec(cps.policy(quote.company_id, "sales").get("auto_send_min_confidence") or 0)
        pr = self.db.get(PartRequest, quote.part_request_id) if quote.part_request_id else None
        confidence = (pr.structured_data or {}).get("intent_confidence") if pr else None
        if confidence is None:
            return False, "Уверенность намерения не определена"
        value = _dec(confidence)
        if not _rating_in_range(value):
            return False, f"Уверенность намерения {value} вне шкалы 0..1"
        return value >= threshold, f"Уверенность намерения {value} ≥ {threshold}"

    def _fitment_ok(self, quote: Quote) -> tuple[bool, str]:
        """VIN-dependent fitment must be proven by the Fitment Engine (4.0).

        intent_confidence only says "the customer asked for a part" — it does
        NOT say "this exact part fits this vehicle". The engine combines
        catalog/OEM/cross-reference knowledge, supplier offers, order history,
        manager confirmations and returns into ONE real fitment_confidence.
        Without the engine (or without a vehicle) nothing VIN-dependent is
        auto-sent — it goes to a manager.
        """
        pr = self.db.get(PartRequest, quote.part_request_id) if quote.part_request_id else None
        if pr is None:
            return False, "Заявка не найдена"
        vehicle_dependent = self._is_vehicle_dependent(pr)
        if not vehicle_dependent:
            return True, "Подбор по артикулу без автомобиля — fitment не требуется"
        from app.services.fitment_service import FitmentService

        result = FitmentService(self.db).evaluate(pr)
        cps = CompanyPolicyService(self.db)
        threshold = _dec(
            cps.policy(quote.company_id, "sales").get("auto_send_min_fitment_confidence") or 0
        )
        value = _dec(result.confidence)
        if not _rating_in_range(value):
            return False, f"fitment_confidence {value} вне шкалы 0..1"
        return (
            value >= threshold,
            f"Подбор по автомобилю: fitment_confidence {value} ≥ {threshold} "
            f"(движок {result.engine_version}, вердикт {result.verdict})",
        )

    def _suppliers_ok(self, quote: Quote) -> tuple[bool, str]:
        cps = CompanyPolicyService(self.db)
        threshold = _dec(
            cps.policy(quote.company_id, "sales").get("auto_send_min_supplier_rating") or 0
        )
        if not _rating_in_range(threshold):
            return False, f"Порог надёжности поставщиков {threshold} вне шкалы 0..1"
        offer_ids = [item.get("offer_id") for item in (quote.items or []) if item.get("offer_id")]
        if not offer_ids:
            return False, "В квоте нет офферов для проверки поставщиков"
        suppliers = self._suppliers_for_offers(offer_ids)
        if not suppliers:
            return False, "Поставщики по офферам не найдены"
        ratings = [_dec((s.settings or {}).get("rating")) for s in suppliers]
        if any(not _rating_in_range(r) for r in ratings):
            return False, "Рейтинг поставщика вне шкалы 0..1 — надёжность не подтверждена"
        worst = min(ratings, default=Decimal("0"))
        return worst >= threshold, f"Надёжность поставщиков {worst} ≥ {threshold}"

    def _standard_ok(self, quote: Quote) -> tuple[bool, str]:
        pr = self.db.get(PartRequest, quote.part_request_id) if quote.part_request_id else None
        if pr is None:
            return False, "Заявка не найдена"
        if pr.missing_fields:
            return False, f"Нестандартный запрос: нет {'/'.join(pr.missing_fields)}"
        if pr.intent != "part_search":
            return False, f"Интент заявки «{pr.intent}» — не поиск детали"
        return True, "Стандартный запрос на подбор детали"

    # --- Helpers ------------------------------------------------------------

    def _thresholds(self, company_id) -> dict[str, Any]:
        cps = CompanyPolicyService(self.db)
        sales = cps.policy(company_id, "sales")
        approval = cps.policy(company_id, "approval")
        return {
            "auto_send_quote": sales.get("auto_send_quote"),
            "auto_send_min_confidence": sales.get("auto_send_min_confidence"),
            "auto_send_min_fitment_confidence": sales.get("auto_send_min_fitment_confidence"),
            "auto_send_min_supplier_rating": sales.get("auto_send_min_supplier_rating"),
            "auto_approve_quote_amount": approval.get("auto_approve_quote_amount"),
        }

    @staticmethod
    def _is_vehicle_dependent(pr: PartRequest) -> bool:
        if pr.vehicle_id is not None:
            return True
        vehicle = (pr.structured_data or {}).get("vehicle") or {}
        return bool(
            isinstance(vehicle, dict)
            and (vehicle.get("vin") or vehicle.get("brand") or vehicle.get("model"))
        )

    def _suppliers_for_offers(self, offer_ids: list[str]) -> list[Supplier]:
        parsed = []
        for raw in offer_ids:
            try:
                parsed.append(uuid.UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        if not parsed:
            return []
        # Select only the supplier ids with DISTINCT — PostgreSQL cannot
        # DISTINCT a full row that contains a json column (suppliers.settings).
        stmt = (
            select(SupplierOffer.supplier_id)
            .where(SupplierOffer.id.in_(parsed))
            .distinct()
        )
        supplier_ids = list(self.db.scalars(stmt).all())
        if not supplier_ids:
            return []
        return list(
            self.db.scalars(select(Supplier).where(Supplier.id.in_(supplier_ids))).all()
        )
