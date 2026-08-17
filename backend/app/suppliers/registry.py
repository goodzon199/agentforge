from __future__ import annotations

from typing import Any

from app.suppliers.base import SupplierAdapter
from app.suppliers.csv import CsvSupplierAdapter
from app.suppliers.http import HttpSupplierAdapter
from app.suppliers.mock import MockSupplierAdapter
from app.suppliers.providers import (
    ArmtekAdapter,
    AvtokontinentAdapter,
    AvtorustAdapter,
    ShatemAdapter,
)
from app.suppliers.rossko import RosskoAdapter


class SupplierRegistry:
    """Registry of supplier adapter backends, keyed by ``adapter.type``."""

    def __init__(self) -> None:
        self._adapters: dict[str, type[SupplierAdapter]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(MockSupplierAdapter)
        self.register(CsvSupplierAdapter)
        self.register(HttpSupplierAdapter)
        self.register(RosskoAdapter)
        # Sprint 4.7 — real provider presets. Each connects through the
        # existing SupplierAdapter contract; none of them changed the core.
        self.register(ArmtekAdapter)
        self.register(ShatemAdapter)
        self.register(AvtorustAdapter)
        self.register(AvtokontinentAdapter)

    def register(self, adapter_cls: type[SupplierAdapter]) -> None:
        self._adapters[adapter_cls.type] = adapter_cls

    def create(
        self,
        adapter_type: str,
        *,
        name: str = "",
        settings: dict[str, Any] | None = None,
    ) -> SupplierAdapter:
        cls = self._adapters.get(adapter_type)
        if cls is None:
            raise ValueError(f"Неизвестный тип адаптера поставщика: {adapter_type}")
        return cls(name=name, settings=settings or {})

    def types(self) -> list[str]:
        return list(self._adapters.keys())

    def is_experimental(self, adapter_type: str) -> bool:
        cls = self._adapters.get(adapter_type)
        if cls is None:
            return False
        return bool(getattr(cls, "experimental", False))


supplier_registry = SupplierRegistry()
