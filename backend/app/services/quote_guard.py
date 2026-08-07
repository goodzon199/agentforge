from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

# "AI формулирует. Система принимает решения." — QuoteGuard is the deterministic
# wall between an LLM's wording and a fact. It validates a sales message against
# the actual Quote and BLOCKS it if any fact (price, brand, article, delivery,
# availability, quantity, currency) does not match. The system never trusts the
# AI with a fact: prices are only computed by the pricing engine, never by the
# sales text.

_VIN_RE = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")

# 8 950 ₽, 8\u00a0950 руб., 8 950,50 ₽
_PRICE_RE = re.compile(
    r"(\d[\d\s\u00a0\u202f]*(?:[.,]\d+)?)\s*(?:₽|руб(?:лей|ля|ли)?\.?|р\.|RUB)",
    re.IGNORECASE,
)

_FOREIGN_CURRENCY_RE = re.compile(
    r"[\$€£₴]|\b(?:USD|EUR|доллар|евро|гривн|грн)\b", re.IGNORECASE
)

# An article-like token: starts with 1-6 latin letters, contains at least one
# digit, total length >= 4 (so vehicle codes like X5 / XDrive don't match).
_ARTICLE_TOKEN_RE = re.compile(r"[A-Z]{1,6}[A-Z0-9/\-]*\d[A-Z0-9/\-]*")

_DAYS_RE = re.compile(r"(\d{1,2})\s*(?:дн|день|дня|дней)", re.IGNORECASE)
_AVAIL_RE = re.compile(r"в\s+наличии\s+(\d{1,2})", re.IGNORECASE)
_QTY_RE = re.compile(r"(\d{1,2})\s*(?:шт|штук|комплект|компл|набор)", re.IGNORECASE)
_ZERO_DAYS = re.compile(r"\b(?:сегодня|сразу|в этот же день)\b", re.IGNORECASE)


@dataclass
class GuardResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "facts": self.facts,
        }


class QuoteGuard:
    """Validates a customer-facing sales message against a Quote."""

    def check(
        self,
        text: str,
        items: Iterable[dict[str, Any]],
        purchase_prices: Iterable[Any] | None = None,
    ) -> GuardResult:
        items = list(items)
        errors: list[str] = []
        facts: dict[str, Any] = {"prices": [], "articles": [], "days": [], "quantities": []}

        customer_amounts = self._customer_amounts(items)
        purchase_amounts = self._decimal_set(purchase_prices or [])
        known_articles = self._normalize_articles([it.get("article", "") for it in items])
        known_brands = {str(it.get("brand", "")).upper() for it in items}
        allowed_days = {
            int(it["delivery_days"])
            for it in items
            if it.get("delivery_days") is not None
        }
        max_avail = max(
            (int(it["quantity_available"]) for it in items if it.get("quantity_available") is not None),
            default=0,
        )

        if not text.strip():
            return GuardResult(passed=False, errors=["Сообщение пустое."], facts=facts)

        cleaned = _VIN_RE.sub(" ", text)

        if _FOREIGN_CURRENCY_RE.search(text):
            errors.append("Обнаружена иностранная валюта — цена должна быть в ₽/руб.")

        for amount, raw in self._extract_amounts(text):
            facts["prices"].append(str(amount))
            if amount in customer_amounts:
                continue
            if amount in purchase_amounts:
                errors.append(
                    f"Цена «{raw}» — внутренняя закупочная цена, клиенту её сообщать нельзя."
                )
            else:
                errors.append(
                    f"Цена «{raw}» не соответствует ни одному предложению в квоте."
                )

        upper = cleaned.upper()
        for token in _ARTICLE_TOKEN_RE.findall(upper):
            token = token.strip(" /-")
            norm = self._normalize_article(token)
            if len(token) < 4 or not norm:
                continue
            facts["articles"].append(token)
            if norm not in known_articles:
                errors.append(
                    f"Товар «{token}» отсутствует в квоте — его нельзя предлагать клиенту."
                )

        mentioned_brands = [
            b for b in known_brands if b and re.search(rf"\b{re.escape(b)}\b", upper)
        ]
        mentioned_articles = [
            a for a in known_articles if a and a in " ".join(facts["articles"])
        ]
        if mentioned_brands and not mentioned_articles:
            errors.append(
                "Упомянут бренд без конкретного товара из квота — предложение неоднозначно."
            )

        for raw in _DAYS_RE.findall(text):
            n = int(raw)
            facts["days"].append(n)
            if n not in allowed_days:
                errors.append(f"Срок «{n} дн» не соответствует квоте.")
        if "завтра" in text.lower() and 1 not in allowed_days:
            errors.append("Срок «завтра» не соответствует квоте.")
        if _ZERO_DAYS.search(text) and 0 not in allowed_days:
            errors.append("Срок «сегодня» не соответствует квоте.")

        for raw in _AVAIL_RE.findall(text):
            n = int(raw)
            facts["quantities"].append(n)
            if n > max_avail:
                errors.append(f"Наличие «{n} шт» превышает квоту поставщиков.")
        for raw in _QTY_RE.findall(text):
            n = int(raw)
            facts["quantities"].append(n)
            if n > max_avail:
                errors.append(f"Количество «{n} шт» недоступно по квоте.")

        return GuardResult(passed=not errors, errors=errors, facts=facts)

    # --- Helpers -----------------------------------------------------------

    @staticmethod
    def _extract_amounts(text: str) -> list[tuple[Decimal, str]]:
        result: list[tuple[Decimal, str]] = []
        for match in _PRICE_RE.finditer(text):
            raw = " ".join(match.group(1).replace("\u00a0", " ").replace("\u202f", " ").split())
            value = raw.replace(",", ".").replace(" ", "")
            try:
                result.append((Decimal(value), raw))
            except InvalidOperation:
                continue
        return result

    @staticmethod
    def _customer_amounts(items: list[dict[str, Any]]) -> set[Decimal]:
        amounts: set[Decimal] = set()
        for it in items:
            for key in ("sale_price", "total_price"):
                raw = it.get(key)
                if raw is None:
                    continue
                try:
                    amounts.add(Decimal(str(raw)))
                except InvalidOperation:
                    continue
        return amounts

    @staticmethod
    def _decimal_set(values: Iterable[Any]) -> set[Decimal]:
        result: set[Decimal] = set()
        for value in values:
            if value is None:
                continue
            try:
                result.add(Decimal(str(value)))
            except InvalidOperation:
                continue
        return result

    @staticmethod
    def _normalize_article(article: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(article).upper())

    def _normalize_articles(self, articles: Iterable[str]) -> set[str]:
        return {self._normalize_article(a) for a in articles if a}


quote_guard = QuoteGuard()
