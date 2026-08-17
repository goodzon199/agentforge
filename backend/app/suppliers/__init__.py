from app.suppliers.base import (
    ExternalOrderResult,
    NormalizedSupplierOffer,
    SupplierAdapter,
    SupplierOrderData,
    SupplierSearchQuery,
)
from app.suppliers.csv import CsvSupplierAdapter
from app.suppliers.errors import (
    SupplierAdapterError,
    SupplierAuthError,
    SupplierConnectionError,
    SupplierParseError,
    SupplierQueryNotSupported,
    SupplierRateLimitError,
    SupplierResponseError,
    SupplierTimeoutError,
)
from app.suppliers.http import HttpSupplierAdapter
from app.suppliers.mock import MockSupplierAdapter
from app.suppliers.normalize import normalize_article
from app.suppliers.providers import (
    ArmtekAdapter,
    AvtokontinentAdapter,
    AvtorustAdapter,
    ShatemAdapter,
)
from app.suppliers.registry import SupplierRegistry, supplier_registry
from app.suppliers.rossko import RosskoAdapter

__all__ = [
    "ArmtekAdapter",
    "AvtokontinentAdapter",
    "AvtorustAdapter",
    "CsvSupplierAdapter",
    "ExternalOrderResult",
    "HttpSupplierAdapter",
    "MockSupplierAdapter",
    "NormalizedSupplierOffer",
    "RosskoAdapter",
    "ShatemAdapter",
    "SupplierAdapter",
    "SupplierAdapterError",
    "SupplierAuthError",
    "SupplierConnectionError",
    "SupplierOrderData",
    "SupplierParseError",
    "SupplierQueryNotSupported",
    "SupplierRateLimitError",
    "SupplierRegistry",
    "SupplierResponseError",
    "SupplierSearchQuery",
    "SupplierTimeoutError",
    "normalize_article",
    "supplier_registry",
]
