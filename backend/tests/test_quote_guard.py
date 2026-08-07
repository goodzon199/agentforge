from __future__ import annotations

from app.services.quote_guard import QuoteGuard

ITEMS = [
    {
        "offer_id": "o1",
        "brand": "BREMBO",
        "article": "P06089",
        "part_name": "Тормозные колодки передние",
        "sale_price": "8840.00",
        "total_price": "8840.00",
        "delivery_days": 2,
        "quantity_available": 4,
    },
    {
        "offer_id": "o2",
        "brand": "TRW",
        "article": "GDB2119",
        "part_name": "Тормозные колодки передние",
        "sale_price": "7930.00",
        "total_price": "7930.00",
        "delivery_days": 1,
        "quantity_available": 3,
    },
]

PURCHASE_PRICES = ["6800.00", "6100.00"]

OK_MESSAGE = (
    "Здравствуйте! Подобрал для вас варианты:\n"
    "⭐ TRW GDB2119 — 7 930 ₽ (срок 1 дн., в наличии 3 шт)\n"
    "• BREMBO P06089 — 8 840 ₽ (срок 2 дн., в наличии 4 шт)\n"
    "Какой вариант вам подходит?"
)


def _check(message):
    return QuoteGuard().check(message, ITEMS, PURCHASE_PRICES)


def test_passes_correct_message():
    result = _check(OK_MESSAGE)
    assert result.passed is True, result.errors
    assert result.errors == []


def test_blocks_wrong_price():
    message = OK_MESSAGE.replace("7 930", "8 950")
    result = _check(message)
    assert result.passed is False
    assert any("не соответствует" in e for e in result.errors)


def test_blocks_purchase_price_leak():
    # 6 100 — закупочная цена TRW, клиенту её сообщать нельзя.
    message = "TRW GDB2119 — 6 100 ₽"
    result = _check(message)
    assert result.passed is False
    assert any("закупочн" in e.lower() for e in result.errors)


def test_blocks_nonexistent_article():
    message = "BREMBO P99999 — 8 840 ₽"
    result = _check(message)
    assert result.passed is False
    assert any("P99999" in e for e in result.errors)


def test_blocks_foreign_currency():
    message = "TRW GDB2119 — $100"
    result = _check(message)
    assert result.passed is False
    assert any("валют" in e.lower() for e in result.errors)


def test_blocks_delivery_mismatch():
    message = "TRW GDB2119 — 7 930 ₽ (срок 7 дней)"
    result = _check(message)
    assert result.passed is False
    assert any("срок" in e.lower() for e in result.errors)


def test_blocks_quantity_over_availability():
    message = "TRW GDB2119 — 7 930 ₽, в наличии 10 шт"
    result = _check(message)
    assert result.passed is False
    assert any("наличи" in e.lower() or "количест" in e.lower() for e in result.errors)


def test_blocks_brand_without_article():
    message = "Предлагаем BREMBO — отличное качество."
    result = _check(message)
    assert result.passed is False
    assert any("бренд" in e.lower() for e in result.errors)


def test_passes_manager_edited_message():
    message = "Здравствуйте! Рекомендую TRW GDB2119 за 7 930 ₽, срок 1 день, в наличии 3 шт."
    result = _check(message)
    assert result.passed is True, result.errors


def test_blocks_empty_message():
    result = _check("")
    assert result.passed is False


def test_facts_collected():
    result = _check(OK_MESSAGE)
    assert result.passed is True
    assert set(result.facts["prices"]) == {"7930", "8840"}
    assert "GDB2119" in result.facts["articles"]
    assert "P06089" in result.facts["articles"]
