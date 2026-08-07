from __future__ import annotations

from typing import Any

# Business-rule defaults for every policy domain (Sprint 3.5 — Company Policy
# Engine). A company stores only its overrides in CompanyPolicy; everything
# else falls back to these defaults, so turning a rule "on" never requires a
# code change — just a settings update.

DEFAULT_PRICING_POLICY: dict[str, Any] = {
    "min_margin_percent": 0.0,  # floor on the applied margin (%)
    "markups": {},  # {"supplier_slug": 5.0} — extra margin per supplier (%)
    "min_profit": 0.0,  # absolute minimum profit (RUB) per offer
    "rounding": 0.01,  # price rounding step (0.01 / 1 / 10 / 50 / 100)
    "allow_discounts": False,
    "max_discount_percent": 0.0,
}

DEFAULT_SUPPLIER_POLICY: dict[str, Any] = {
    "priority": [],  # supplier slugs, first = highest priority
    "blocked_brands": [],
    "favorite_brands": [],
    "max_lead_days": None,  # drop offers with a longer lead time
    "min_rating": 0.0,  # supplier rating from supplier.settings["rating"]
    "max_variants": 5,  # max offers kept for pricing / the quote
}

DEFAULT_APPROVAL_POLICY: dict[str, Any] = {
    "auto_approve_quote_amount": None,  # quotes ≤ this (RUB) send automatically
    "manager_above_amount": None,
    "owner_above_amount": None,
    "requires_manager": [],  # action types that always need a manager
    "requires_owner": [],  # action types that always need the owner
}

DEFAULT_SALES_POLICY: dict[str, Any] = {
    "auto_send_quote": False,
    "use_emojis": True,
    "formal_style": False,
    "show_analogs": True,
    "show_lead_times": True,
    "show_stock": True,
}

DEFAULT_SECURITY_POLICY: dict[str, Any] = {
    "permissions": {},  # mirrored to company.settings.permissions (PermissionEngine)
}

DEFAULT_POLICIES: dict[str, dict[str, Any]] = {
    "pricing": DEFAULT_PRICING_POLICY,
    "supplier": DEFAULT_SUPPLIER_POLICY,
    "approval": DEFAULT_APPROVAL_POLICY,
    "sales": DEFAULT_SALES_POLICY,
    "security": DEFAULT_SECURITY_POLICY,
}


def merge_policy(default: dict[str, Any], stored: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-merge stored overrides onto the built-in defaults.

    Nested dicts merge key-by-key; lists and scalars are replaced wholesale.
    """
    result = dict(default)
    if not stored:
        return result
    for key, value in stored.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = value
    return result
