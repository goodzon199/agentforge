"""Platform permission catalog (sprint 5.9.2).

Single source of truth for permissions a pack may declare. The manifest
only *requests* entries from this catalog; rights are granted exclusively
by platform admins (docs/PACK_SECURITY.md, 5.9.2). An unknown permission
in a manifest is a validation error, never a silent acceptance.

The catalog deliberately lives in code: shipping a new permission is a
platform-level security decision that must go through review, not a data
change.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class RiskLevel(str, enum.Enum):
    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"


@dataclass(frozen=True)
class PermissionSpec:
    name: str
    description: str
    risk_level: RiskLevel
    resource_type: str


_CATALOG: tuple[PermissionSpec, ...] = (
    PermissionSpec("customer.read", "Чтение профилей клиентов компании", RiskLevel.medium, "customer"),
    PermissionSpec("customer.write", "Изменение профилей клиентов", RiskLevel.high, "customer"),
    PermissionSpec("conversation.read", "Чтение переписок компании", RiskLevel.medium, "conversation"),
    PermissionSpec("conversation.write", "Создание и изменение переписок", RiskLevel.medium, "conversation"),
    PermissionSpec("message.read", "Чтение сообщений", RiskLevel.low, "message"),
    PermissionSpec("message.write", "Отправка сообщений от имени компании", RiskLevel.low, "message"),
    PermissionSpec("memory.read", "Чтение долговременной памяти агентов", RiskLevel.high, "memory"),
    PermissionSpec("memory.write", "Запись в память агентов", RiskLevel.medium, "memory"),
    PermissionSpec("calendar.read", "Чтение календарей бронирований", RiskLevel.medium, "calendar"),
    PermissionSpec("calendar.write", "Создание и изменение бронирований в календаре", RiskLevel.high, "calendar"),
    PermissionSpec("supplier.search", "Поиск по каталогу поставщиков", RiskLevel.medium, "supplier"),
    PermissionSpec("supplier.order", "Оформление заказов у поставщиков", RiskLevel.high, "supplier"),
    PermissionSpec("quote.read", "Чтение ценовых предложений", RiskLevel.medium, "quote"),
    PermissionSpec("quote.create", "Создание ценовых предложений", RiskLevel.medium, "quote"),
    PermissionSpec("quote.send", "Отправка предложений клиентам", RiskLevel.medium, "quote"),
    PermissionSpec("order.read", "Чтение заказов", RiskLevel.medium, "order"),
    PermissionSpec("order.create", "Создание заказов", RiskLevel.high, "order"),
    PermissionSpec("llm.use", "Использование LLM-бюджета платформы", RiskLevel.medium, "llm"),
    PermissionSpec("tool.execute", "Вызов инструментов платформы", RiskLevel.high, "tool"),
    # Beauty pack verticals (declared in its manifest).
    PermissionSpec("booking.create", "Создание бронирований", RiskLevel.high, "booking"),
    PermissionSpec("notification.send", "Отправка уведомлений клиентам", RiskLevel.medium, "notification"),
)

CATALOG: dict[str, PermissionSpec] = {spec.name: spec for spec in _CATALOG}

# Built-in packs trusted at the moment of the 5.9.2 migration: their
# declared permissions become grants exactly once (grant_source=migration_bootstrap).
BUILTIN_BOOTSTRAP_PACKS = frozenset({"autoparts", "beauty"})


def is_known(permission: str) -> bool:
    return permission in CATALOG


def get_spec(permission: str) -> PermissionSpec | None:
    return CATALOG.get(permission)


def risk_of(permission: str) -> RiskLevel | None:
    spec = CATALOG.get(permission)
    return spec.risk_level if spec else None


def unknown_permissions(names: list[str] | None) -> list[str]:
    """Return manifest-declared permissions missing from the catalog."""
    return [p for p in (names or []) if not is_known(p)]
