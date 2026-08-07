from __future__ import annotations


class SupplierAdapterError(Exception):
    """Base class for normalized supplier adapter failures.

    The platform never crashes on a supplier error: callers (parts search,
    health checks) treat any ``SupplierAdapterError`` as a failed attempt and
    surface the friendly ``message`` (in Russian) to operators.
    """

    kind = "supplier_error"

    def __init__(self, message: str, *, retriable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retriable = retriable

    def __str__(self) -> str:
        return self.message


class SupplierConnectionError(SupplierAdapterError):
    """Network/DNS/transport failure — the provider is unreachable."""

    kind = "connection"


class SupplierTimeoutError(SupplierAdapterError):
    """The provider did not answer within the configured timeout."""

    kind = "timeout"


class SupplierAuthError(SupplierAdapterError):
    """401/403 — the configured credentials are missing or invalid."""

    kind = "auth"


class SupplierRateLimitError(SupplierAdapterError):
    """429 — the provider's rate limit was exhausted and not resolved by retry."""

    kind = "rate_limit"


class SupplierResponseError(SupplierAdapterError):
    """The provider answered with an unexpected HTTP error status."""

    kind = "response"


class SupplierParseError(SupplierAdapterError):
    """The provider payload could not be mapped to the platform contract."""

    kind = "parse"
