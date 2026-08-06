from __future__ import annotations

from decimal import Decimal

from app.suppliers.base import NormalizedSupplierOffer, SupplierAdapter, SupplierSearchQuery
from app.suppliers.normalize import normalize_article


class MockSupplierAdapter(SupplierAdapter):
    """Stable, deterministic demo supplier.

    Serves a fixed catalog (BREMBO P06089 / TRW GDB2119). Used as the default
    demo adapter and as a fixture in tests.
    """

    type = "mock"

    CATALOG: list[tuple[str, str, str, str, int, int]] = [
        # (brand, article, part_name, price, quantity, delivery_days)
        ("BREMBO", "P06089", "Тормозные колодки передние", "6800.00", 4, 2),
        ("TRW", "GDB2119", "Тормозные колодки передние", "6100.00", 3, 1),
    ]

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        article = normalize_article(query.article)
        offers: list[NormalizedSupplierOffer] = []
        for brand, art, name, price, qty, days in self.CATALOG:
            if article and not self._matches(article, normalize_article(art)):
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
