from __future__ import annotations

import csv
import os
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from app.suppliers.base import NormalizedSupplierOffer, SupplierAdapter, SupplierSearchQuery
from app.suppliers.normalize import normalize_article


class CsvSupplierAdapter(SupplierAdapter):
    """Reads a supplier feed from a CSV file.

    Column mapping is configured via ``settings``::

        {
            "file_path": "/data/suppliers/brembo.csv",
            "delimiter": ";",
            "encoding": "utf-8",
            "columns": {
                "brand": "brand",
                "article": "article",
                "name": "name",
                "price": "price",
                "quantity": "quantity",
                "delivery_days": "delivery_days",
            },
        }
    """

    type = "csv"

    _DEFAULT_COLUMNS: ClassVar[dict[str, str]] = {
        "brand": "brand",
        "article": "article",
        "name": "name",
        "price": "price",
        "quantity": "quantity",
        "delivery_days": "delivery_days",
    }

    def __init__(self, *, name: str = "", settings: dict[str, Any] | None = None) -> None:
        super().__init__(name=name, settings=settings)
        self.file_path = str(self.settings.get("file_path", "") or "")
        self.delimiter = str(self.settings.get("delimiter", ",") or ",")
        self.encoding = str(self.settings.get("encoding", "utf-8") or "utf-8")
        columns = self.settings.get("columns") or {}
        self.columns = {**self._DEFAULT_COLUMNS, **columns}

    def _read_rows(self) -> list[dict[str, str]]:
        if not self.file_path or not os.path.exists(self.file_path):
            raise FileNotFoundError(f"CSV файл поставщика не найден: {self.file_path}")
        with open(self.file_path, encoding=self.encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=self.delimiter)
            return [dict(row) for row in reader]

    def _cell(self, row: dict[str, str], key: str) -> str:
        column = self.columns.get(key, key)
        return (row.get(column) or "").strip()

    @staticmethod
    def _price(value: str) -> Decimal | None:
        if not value:
            return None
        try:
            return Decimal(value.replace(",", ".").replace(" ", ""))
        except InvalidOperation:
            return None

    @staticmethod
    def _int(value: str) -> int | None:
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    async def search(self, query: SupplierSearchQuery) -> list[NormalizedSupplierOffer]:
        rows = self._read_rows()
        query_article = normalize_article(query.article)
        offers: list[NormalizedSupplierOffer] = []
        for row in rows:
            article = self._cell(row, "article")
            if query_article and not self._matches(query_article, normalize_article(article)):
                continue
            offers.append(
                NormalizedSupplierOffer(
                    supplier_name=self.name,
                    brand=self._cell(row, "brand") or self.name,
                    article=article,
                    part_name=self._cell(row, "name"),
                    purchase_price=self._price(self._cell(row, "price")),
                    quantity=self._int(self._cell(row, "quantity")),
                    delivery_days=self._int(self._cell(row, "delivery_days")),
                )
            )
        return offers

    @staticmethod
    def _matches(query_article: str, feed_article: str) -> bool:
        return query_article in feed_article or feed_article in query_article
