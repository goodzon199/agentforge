from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CatalogFitment,
    CrossReference,
    Order,
    PartFitmentEvidence,
    PartRequest,
    PartReturn,
    SupplierOffer,
)
from app.services.vin_decode import VinDecode, decode_vin

# Version of the combination logic — bump on any formula change so stored
# snapshots can be re-computed without guessing.
FITMENT_ENGINE_VERSION = "4.0.0"

# --- Source weights (explainability: the same table drives the UI) ---------
# Calibration: catalog + cross alone land just under 0.9 (a fresh VIN request
# goes to a manager — never auto-send on catalog hope); once order history /
# manager confirmations accumulate, confidence crosses 0.9 and Controlled Auto
# may act. A return (weight 5, score 0) drags even a strong catalog below 0.5.
WEIGHTS: dict[str, float] = {
    "vin": 0.4,
    "catalog": 3.0,
    "oem": 1.8,
    "cross": 0.8,
    "supplier_direct": 0.8,
    "supplier_cross": 0.3,
    "evidence": 4.0,
    "return": 5.0,  # negative source: drags the mean down hard
}

# The "doubt prior": a vehicle-dependent request with zero evidence stays
# doubtful (confidence 0), NOT a blank 0.5 — so nothing auto-sends on hope.
_DOUBT_PRIOR_WEIGHT = 0.3

# Human-readable labels for the explainability UI (sprint 4.1).
_SOURCE_LABEL: dict[str, str] = {
    "vin": "VIN-декодирование",
    "catalog": "Каталог совместимости",
    "oem": "OEM-номер",
    "cross": "Кросс-ссылка",
    "supplier_direct": "Предложения поставщиков",
    "supplier_cross": "Кросс-предложения",
    "evidence": "История заказов и подтверждений",
    "return": "Возвраты",
    "manager": "Подтверждение менеджера",
}


@dataclass
class FitmentScore:
    """One source's vote in the fitment decision."""

    source: str
    weight: float
    score: float  # 0..1; a negative source uses weight with score 0
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FitmentExplain:
    """Sprint 4.1 — the explainability view of a FitmentResult.

    Adds the traffic-light level, the human-readable confirmations (checks)
    and the risk warnings (warnings) on top of the raw engine output, so the
    UI can show "почему 94%" without a spreadsheet.
    """

    level: str  # high / medium / low
    result: FitmentResult
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            **self.result.to_dict(),
            "checks": self.checks,
            "warnings": self.warnings,
        }


@dataclass
class FitmentResult:
    """The engine's verdict for one part request.

    ``confidence`` is a real fitment confidence on 0..1 — the combination of
    catalog/OEM/cross-reference knowledge, supplier offers, order history,
    manager confirmations and returns. It is NOT the intent confidence.
    """

    confidence: float
    vehicle_dependent: bool
    verdict: str
    sources: list[FitmentScore] = field(default_factory=list)
    vin: dict[str, Any] = field(default_factory=dict)
    computed_at: str = ""
    engine_version: str = FITMENT_ENGINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "vehicle_dependent": self.vehicle_dependent,
            "verdict": self.verdict,
            "sources": [s.to_dict() for s in self.sources],
            "vin": self.vin,
            "computed_at": self.computed_at,
            "engine_version": self.engine_version,
        }


class FitmentService:
    """Sprint 4.0 — the Fitment Engine.

    Combines every signal the business already generates into ONE explainable
    ``confidence``: VIN decode, catalog fitment (article+vehicle), OEM
    numbers, cross references (incl. Rossko ``is_cross`` offers), supplier
    offer consistency, order history for the same vehicle+article, manager
    confirmations (Shadow Comparison + approved feedback) and — the strongest
    negative — part returns. The result is the single source of truth for
    ``auto_send_service`` and analytics, replacing the intent-confidence proxy.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Public entry ------------------------------------------------------

    def evaluate(self, part_request: PartRequest) -> FitmentResult:
        """Compute the fitment confidence for one part request (read-only)."""
        vehicle_dependent = self._vehicle_dependent(part_request)
        vin = self._vin_info(part_request)
        if not vehicle_dependent:
            # Article-only search: there is no vehicle to fit against, so
            # nothing to prove — confidence is not a blocker.
            return FitmentResult(
                confidence=1.0,
                vehicle_dependent=False,
                verdict="na",
                sources=[],
                vin=vin,
                computed_at=_now_iso(),
            )

        scores: list[FitmentScore] = []
        scores += self._catalog_scores(part_request, vin)
        scores += self._cross_scores(part_request, self._vehicle(part_request))
        scores += self._supplier_scores(part_request)
        scores += self._evidence_scores(part_request)
        scores += self._return_scores(part_request)

        confidence = self._combine(scores)
        verdict = (
            "confirmed"
            if confidence >= 0.9
            else "plausible"
            if confidence >= 0.5
            else "uncertain"
        )
        return FitmentResult(
            confidence=round(confidence, 4),
            vehicle_dependent=True,
            verdict=verdict,
            sources=scores,
            vin=vin,
            computed_at=_now_iso(),
        )

    def explain(self, part_request: PartRequest) -> FitmentExplain:
        """Sprint 4.1 — why this confidence, in plain language.

        Produces the traffic light (high/medium/low), a list of concrete
        confirmations ("каталог TRW GDB3410 подходит X5 2016") and a list of
        risk warnings ("есть возврат: колодки не подошли"). Drives the
        «Почему?» panel in the UI.
        """
        result = self.evaluate(part_request)
        level = "high" if result.confidence >= 0.9 else "medium" if result.confidence >= 0.5 else "low"
        checks: list[str] = []
        warnings: list[str] = []

        if not result.vehicle_dependent:
            checks.append("Запрос без автомобиля: проверять нечего, уверенность не блокирует.")
            return FitmentExplain(level="high", result=result, checks=checks, warnings=warnings)

        if result.vin.get("vin"):
            if result.vin.get("valid"):
                year = f", {result.vin['year']} г." if result.vin.get("year") else ""
                checks.append(f"VIN валиден по ISO 3779: {result.vin['brand']}{year}")
            else:
                warnings.append(f"VIN не прошёл контрольную сумму: {result.vin.get('vin', '')}")

        for s in result.sources:
            detail = s.detail or _SOURCE_LABEL.get(s.source, s.source)
            if s.source == "return":
                warnings.append(detail)
            elif s.score > 0:
                checks.append(detail)
            elif s.source == "vin":
                warnings.append(detail)
            else:
                warnings.append(detail or _SOURCE_LABEL.get(s.source, s.source))

        if result.verdict == "uncertain":
            warnings.append("Слишком мало подтверждений — требуется проверка менеджера.")
        return FitmentExplain(level=level, result=result, checks=checks, warnings=warnings)

    def verify(
        self,
        part_request: PartRequest,
        *,
        user_id: uuid.UUID | None,
        article: str,
        brand: str = "",
        result: str = "confirmed",
    ) -> PartFitmentEvidence:
        """Sprint 4.1 — a manager's [✓]/[✕] verdict becomes evidence.

        Confirmed → confidence 1.0, rejected → 0.0 (drags the mean down like a
        return). The row records who verified and updates the request's
        ``structured_data["fitment"]`` snapshot so the UI and analytics see the
        new confidence immediately.
        """
        verdict = "confirmed" if result == "confirmed" else "rejected"
        evidence = PartFitmentEvidence(
            company_id=part_request.company_id,
            part_request_id=part_request.id,
            vehicle_id=part_request.vehicle_id,
            article=(article or part_request.article or "").strip(),
            brand=brand,
            source="manager",
            result=verdict,
            confidence=1.0 if verdict == "confirmed" else 0.0,
            user_id=user_id,
            detail={"result": verdict, "part_request_id": str(part_request.id)},
        )
        self.db.add(evidence)
        self.db.flush()

        structured = dict(part_request.structured_data or {})
        structured["fitment"] = self.snapshot(part_request)
        part_request.structured_data = structured
        self.db.flush()
        return evidence

    def evaluate_for_quote(self, quote) -> FitmentResult:
        """Evaluate the request behind a quote (used by auto-send)."""
        pr = self.db.get(PartRequest, quote.part_request_id) if quote.part_request_id else None
        if pr is None:
            return FitmentResult(0.0, True, "uncertain", [], {}, _now_iso())
        return self.evaluate(pr)

    def snapshot(self, part_request: PartRequest) -> dict[str, Any]:
        """The persistent snapshot written into ``structured_data["fitment"]``."""
        return self.evaluate(part_request).to_dict()

    # --- Accumulating evidence (learning moat) -----------------------------

    def record_order_evidence(
        self,
        part_request: PartRequest,
        order: Order,
    ) -> None:
        """An order for this request confirms the article fits the vehicle."""
        for item in order.items or []:
            article = str(item.get("article") or "").strip()
            if not article:
                continue
            self.db.add(
                PartFitmentEvidence(
                    company_id=order.company_id,
                    part_request_id=order.part_request_id,
                    vehicle_id=part_request.vehicle_id,
                    article=article,
                    brand=str(item.get("brand") or "").strip(),
                    source="order_history",
                    confidence=1.0,
                    detail={"order_id": str(order.id), "order_number": order.order_number},
                )
            )
        self.db.flush()

    def record_manager_evidence(
        self,
        part_request: PartRequest,
        *,
        source: str,
        confidence: float,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """A manager confirmed the pick (Shadow match / approved unchanged)."""
        article = (part_request.article or "").strip()
        if not article:
            return
        self.db.add(
            PartFitmentEvidence(
                company_id=part_request.company_id,
                part_request_id=part_request.id,
                vehicle_id=part_request.vehicle_id,
                article=article,
                brand="",
                source=source,
                confidence=confidence,
                detail=detail or {},
            )
        )
        self.db.flush()

    def record_return(
        self,
        part_request: PartRequest,
        *,
        reason: str,
        status: str = "returned",
        supplier_id: uuid.UUID | None = None,
    ) -> None:
        """A returned/wrong-fit part — the strongest negative signal.

        ``supplier_id`` (sprint 4.2) attributes the return to the supplier
        that supplied the bad part, so the return rate lands on the right
        supplier's scoreboard.
        """
        self.db.add(
            PartReturn(
                company_id=part_request.company_id,
                supplier_id=supplier_id,
                part_request_id=part_request.id,
                quote_id=None,
                vehicle_id=part_request.vehicle_id,
                article=part_request.article or "",
                brand="",
                reason=reason,
                status=status,
                returned_at=datetime.now(UTC),
            )
        )
        self.db.flush()

    # --- Source collectors -------------------------------------------------

    @staticmethod
    def _vehicle_dependent(pr: PartRequest) -> bool:
        if pr.vehicle_id is not None:
            return True
        vehicle = (pr.structured_data or {}).get("vehicle") or {}
        return bool(
            isinstance(vehicle, dict)
            and (vehicle.get("vin") or vehicle.get("brand") or vehicle.get("model"))
        )

    def _vin_info(self, pr: PartRequest) -> dict[str, Any]:
        raw = ""
        vehicle = self._vehicle(pr)
        if vehicle is not None and getattr(vehicle, "vin", None):
            raw = vehicle.vin
        if not raw:
            vehicle_data = (pr.structured_data or {}).get("vehicle") or {}
            raw = vehicle_data.get("vin", "")
        decoded: VinDecode = decode_vin(raw)
        return {
            "vin": raw,
            "valid": decoded.valid,
            "brand": decoded.brand,
            "year": decoded.year,
            "reason": decoded.reason,
        }

    def _catalog_scores(self, pr: PartRequest, vin: dict[str, Any]) -> list[FitmentScore]:
        article = _norm(pr.article)
        if not article:
            return []
        rows = self.db.scalars(
            select(CatalogFitment).where(
                CatalogFitment.company_id == pr.company_id,
                CatalogFitment.article == article,
            )
        ).all()
        vehicle = self._vehicle(pr)
        scores: list[FitmentScore] = []
        brand_hit = False
        for row in rows:
            fits = self._catalog_fits(row, vehicle)
            if fits:
                brand_hit = True
                scores.append(
                    FitmentScore(
                        source="catalog",
                        weight=WEIGHTS["catalog"],
                        score=_to_float(row.confidence, 0.9),
                        detail=(
                            f"{row.article} → {row.vehicle_brand} {row.vehicle_model} "
                            f"[{row.year_from or '-'}..{row.year_to or '-'}] {row.engine}"
                        ),
                    )
                )
        if vin.get("valid") and vin.get("brand"):
            vehicle_brand = _norm((vehicle.brand if vehicle is not None else "") or "")
            if vehicle_brand and _norm(vin["brand"]) != vehicle_brand:
                scores.append(
                    FitmentScore(
                        source="vin",
                        weight=WEIGHTS["vin"],
                        score=0.0,
                        detail=f"VIN {vin['brand']} ≠ заявленный {vehicle.brand}",
                    )
                )
            elif not brand_hit:
                scores.append(
                    FitmentScore(
                        source="vin",
                        weight=WEIGHTS["vin"],
                        score=0.4,
                        detail=f"VIN распознан: {vin['brand']}, каталог по артикулу не найден",
                    )
                )
        if not brand_hit:
            # OEM check: is the requested article itself an OEM number?
            oem = self.db.scalars(
                select(CatalogFitment).where(
                    CatalogFitment.company_id == pr.company_id,
                    CatalogFitment.oem_article == article,
                )
            ).all()
            if oem:
                scores.append(
                    FitmentScore(
                        source="oem",
                        weight=WEIGHTS["oem"],
                        score=max(_to_float(r.confidence, 0.9) for r in oem),
                        detail=f"{article} — OEM-номер, известен в каталоге",
                    )
                )
        return scores

    def _cross_scores(self, pr: PartRequest, vehicle) -> list[FitmentScore]:
        """Cross references only count when the target article itself has a
        catalog fitment for THIS vehicle — otherwise "article X == article Y"
        proves nothing about the car in the request."""
        article = _norm(pr.article)
        if not article:
            return []
        rows = self.db.scalars(
            select(CrossReference).where(
                CrossReference.company_id == pr.company_id,
                CrossReference.source_article == article,
            )
        ).all()
        scores: list[FitmentScore] = []
        for row in rows:
            if row.target_article == article:
                continue  # self-reference
            target = self._catalog_fit_for(row.target_article, pr.company_id, vehicle)
            if target is None:
                continue  # no vehicle fitment for the cross target — no proof
            score = min(
                _to_float(row.confidence, 0.8),
                _to_float(target.confidence, 0.9),
            )
            scores.append(
                FitmentScore(
                    source="cross",
                    weight=WEIGHTS["cross"],
                    score=score,
                    detail=f"{article} == {row.target_brand} {row.target_article} "
                    f"(подходит {target.vehicle_brand} {target.vehicle_model})",
                )
            )
        return scores

    def _catalog_fit_for(
        self, article: str, company_id: uuid.UUID, vehicle
    ) -> CatalogFitment | None:
        """The best catalog fitment record for an article + vehicle, if any."""
        if vehicle is None:
            return None
        rows = self.db.scalars(
            select(CatalogFitment).where(
                CatalogFitment.company_id == company_id,
                CatalogFitment.article == article,
            )
        ).all()
        for row in rows:
            if self._catalog_fits(row, vehicle):
                return row
        return None

    def _supplier_scores(self, pr: PartRequest) -> list[FitmentScore]:
        offers = self.db.scalars(
            select(SupplierOffer).where(SupplierOffer.part_request_id == pr.id)
        ).all()
        if not offers:
            return []
        direct = [o for o in offers if not o.is_cross]
        crosses = [o for o in offers if o.is_cross]
        scores: list[FitmentScore] = []
        if direct:
            articles = {_norm(o.article) for o in direct if o.article}
            match = any(a and a == _norm(pr.article) for a in articles)
            scores.append(
                FitmentScore(
                    source="supplier_direct",
                    weight=WEIGHTS["supplier_direct"],
                    score=0.9 if match else 0.4,
                    detail=(
                        f"{len(direct)} прямых предложений"
                        + ("" if match else ", артикул не совпадает с заявкой")
                    ),
                )
            )
        if crosses:
            scores.append(
                FitmentScore(
                    source="supplier_cross",
                    weight=WEIGHTS["supplier_cross"],
                    score=0.5,
                    detail=f"{len(crosses)} кросс-предложений (например, Rossko)",
                )
            )
        return scores

    def _evidence_scores(self, pr: PartRequest) -> list[FitmentScore]:
        """Accumulated human/order evidence: order history + confirmations."""
        if pr.vehicle_id is None and _norm(pr.article) == "":
            return []
        stmt = select(PartFitmentEvidence).where(
            PartFitmentEvidence.company_id == pr.company_id
        )
        stmt = stmt.where(PartFitmentEvidence.article == _norm(pr.article))
        if pr.vehicle_id is not None:
            stmt = stmt.where(PartFitmentEvidence.vehicle_id == pr.vehicle_id)
        rows = list(self.db.scalars(stmt).unique().all())
        scores: list[FitmentScore] = []
        for row in rows:
            # A rejected manager verdict is a hard negative, like a return.
            if row.result == "rejected":
                scores.append(
                    FitmentScore(
                        source="manager",
                        weight=WEIGHTS["return"],
                        score=0.0,
                        detail="менеджер отклонил этот артикул для этого авто",
                    )
                )
                continue
            score = max(0.0, _to_float(row.confidence, 0.0))
            detail = row.source
            if row.result == "confirmed":
                detail = "подтверждено менеджером"
            elif row.source == "order_history":
                num = (row.detail or {}).get("order_number")
                if num:
                    detail = f"заказ {num} на этот артикул/авто"
            scores.append(
                FitmentScore(
                    source="evidence",
                    weight=WEIGHTS["evidence"],
                    score=score,
                    detail=detail,
                )
            )
        return scores

    def _return_scores(self, pr: PartRequest) -> list[FitmentScore]:
        """Returns are negative: their weight participates but score is 0."""
        if pr.vehicle_id is None and _norm(pr.article) == "":
            return []
        stmt = select(PartReturn).where(PartReturn.company_id == pr.company_id)
        if _norm(pr.article):
            stmt = stmt.where(PartReturn.article == _norm(pr.article))
        if pr.vehicle_id is not None:
            stmt = stmt.where(PartReturn.vehicle_id == pr.vehicle_id)
        rows = list(self.db.scalars(stmt).unique().all())
        return [
            FitmentScore(
                source="return",
                weight=WEIGHTS["return"],
                score=0.0,
                detail=f"возврат: {row.reason or row.status}",
            )
            for row in rows
        ]

    # --- Helpers -----------------------------------------------------------

    def _vehicle(self, pr: PartRequest):
        if pr.vehicle_id is None:
            return None
        from app.models import Vehicle

        return self.db.get(Vehicle, pr.vehicle_id)

    @staticmethod
    def _catalog_fits(row: CatalogFitment, vehicle) -> bool:
        if vehicle is None:
            return False
        brand = _norm(row.vehicle_brand)
        model = _norm(row.vehicle_model)
        v_brand = _norm(vehicle.brand)
        v_model = _norm(vehicle.model)
        if brand and brand != v_brand:
            return False
        if model and model != v_model:
            return False
        if row.year_from is not None and vehicle.year is not None and vehicle.year < row.year_from:
            return False
        return not (
            row.year_to is not None and vehicle.year is not None and vehicle.year > row.year_to
        )

    @staticmethod
    def _combine(scores: list[FitmentScore]) -> float:
        """Weighted mean with a doubt prior. Returns drag the mean to 0."""
        numerator = _DOUBT_PRIOR_WEIGHT * 0.0
        denominator = _DOUBT_PRIOR_WEIGHT
        for s in scores:
            denominator += s.weight
            numerator += s.weight * s.score
        if denominator <= 0:
            return 0.0
        value = numerator / denominator
        return min(1.0, max(0.0, value))


def _norm(value: str | None) -> str:
    return "".join((value or "").upper().split())


def _to_float(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
