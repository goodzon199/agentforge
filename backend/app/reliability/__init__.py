from app.reliability.circuit_breaker import (
    BreakerState,
    CircuitBreaker,
    breaker_registry,
    get_breaker,
)
from app.reliability.errors import (
    FAILURE_CODES,
    TRANSIENT,
    FailureKind,
    classify_exception,
    from_llm_kind,
    from_llm_status,
    from_supplier_kind,
)
from app.reliability.retry import RetryPolicy, get_policy

__all__ = [
    "BREAKER_NAMES",
    "BreakerState",
    "CircuitBreaker",
    "FAILURE_CODES",
    "FailureKind",
    "RetryPolicy",
    "TRANSIENT",
    "breaker_registry",
    "classify_exception",
    "from_llm_kind",
    "from_llm_status",
    "from_supplier_kind",
    "get_breaker",
    "get_policy",
]

# The external services protected by a circuit breaker (sprint 3.5).
BREAKER_NAMES = ("ollama", "rossko", "smtp", "http")
