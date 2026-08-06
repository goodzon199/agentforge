from __future__ import annotations


def normalize_article(value: str) -> str:
    """Normalize a part article: uppercase, keep only alphanumeric characters.

    ``"BREMBO P06089"``, ``"p06089"`` and ``"p060-89"`` all become ``"P06089"``.
    """
    return "".join(ch for ch in value.upper() if ch.isalnum())
