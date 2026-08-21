from __future__ import annotations

"""AgentOS platform extraction — shared contract package.

Pure Python. No SQLAlchemy models, no services, no domain logic. Both
``core-service`` and ``autoparts-service`` depend on this package for status
enums, role constants, event schemas, the internal-HTTP client, the pack SDK,
the workflow SDK and the agent/tool SDK (sprint 5.4). This keeps the platform
core free of any automotive-domain import.
"""

__all__ = [
    "agents",
    "events",
    "internal",
    "pack",
    "roles",
    "statuses",
    "tools",
    "workflow",
]
