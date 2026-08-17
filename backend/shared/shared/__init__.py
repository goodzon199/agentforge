from __future__ import annotations

"""AgentOS platform extraction — shared contract package.

Pure Python. No SQLAlchemy models, no services, no domain logic. Both
``core-service`` and ``autoparts-service`` depend on this package for status
enums, role constants, event schemas and the internal-HTTP client. This keeps
the platform core free of any automotive-domain import.
"""

__all__ = ["events", "internal", "roles", "statuses"]