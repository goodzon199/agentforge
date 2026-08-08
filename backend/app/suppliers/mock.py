from __future__ import annotations

from decimal import Decimal

from app.suppliers.base import NormalizedSupplierOffer, SupplierAdapter, SupplierSearchQuery
from app.suppliers.normalize import normalize_article


class MockSupplierAdapter(SupplierAdapter):
    """Stable, deterministic demo supplier.

    Serves a small fixed catalog (brake pads). Filters by article when given;
    otherwise matches the query text against per-item keywords so a request for
    oil does not return pads. Used as the default demo adapter and as a fixture
    in tests. Real parts (e.g. engine oil) must come from live suppliers such as
    Rossko so prices are genuine.
    """

    type = "mock"

    CATALOG: list[tuple[str, str, str, str, int, int, tuple[str, ...]]] = [
        # (brand, article, part_name, price, quantity, delivery_days, keywords)
        ("BREMBO", "P06089", "Тормозные колодки передние", "6800.00", 4, 2, ("колодк", "тормозн")),
        ("TRW", "GDB2119", "Тормозные колодки передние", "6100.00", 3, 1, ("колодк", "тормозн")),
    ]

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        article = normalize_article(query.article)
        text = f"{query.part_name} {query.brand}".strip().lower()
        offers: list[NormalizedSupplierOffer] = []
        for brand, art, name, price, qty, days, keywords in self.CATALOG:
            if article and not self._matches(article, normalize_article(art)):
                continue
            if not article and text and not any(kw in text for kw in keywords):
                continue
            offers.append(
                NormalizedSupplierOffer(
                    supplier_name=self.name,
                    brand=brand,
                    article=art,
                    part_name=name,
                    purchase_price=Decimal(price),
                    quantity=qty,
                    delivery_days=days,
                )
            )
        return offers

    @staticmethod
    def _matches(query_article: str, catalog_article: str) -> bool:
        return query_article in catalog_article or catalog_article in query_article
