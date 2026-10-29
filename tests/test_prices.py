from decimal import Decimal

import pytest

from menubench.prices import ParsedPrice, parse_price, split_trailing_price
from menubench.schema import PriceKind


@pytest.mark.parametrize(
    ("text", "value", "currency"),
    [
        ("350 ₽", "350", "RUB"),
        ("350₽", "350", "RUB"),
        ("1 150 ₽", "1150", "RUB"),
        ("1 150 р.", "1150", "RUB"),
        ("350 руб.", "350", "RUB"),
        ("350", "350", None),
        ("350,-", "350", None),
        ("$12.50", "12.50", "USD"),
        ("12.50", "12.50", None),
        ("$12", "12", "USD"),
        ("€4.25", "4.25", "EUR"),
        ("4,25 €", "4.25", "EUR"),
        ("1 200 ₸", "1200", "KZT"),
    ],
)
def test_prices(text: str, value: str, currency: str | None) -> None:
    assert parse_price(text) == ParsedPrice(Decimal(value), currency=currency)


@pytest.mark.parametrize(
    "text", ["250 г", "350 мл", "25 см", '12"', "10:00", "8 800 555-35-35", "0,25", "S", "Борщ", "", "2024 год"]
)
def test_not_prices(text: str) -> None:
    assert parse_price(text) is None


def test_from_and_range() -> None:
    assert parse_price("от 300 ₽") == ParsedPrice(Decimal(300), None, PriceKind.FROM, "RUB")
    assert parse_price("300–450 ₽") == ParsedPrice(Decimal(300), Decimal(450), PriceKind.RANGE, "RUB")
    assert parse_price("$8 - $12") == ParsedPrice(Decimal(8), Decimal(12), PriceKind.RANGE, "USD")


def test_split_trailing_price() -> None:
    assert split_trailing_price("Борщ ........ 350 ₽") == ("Борщ", ParsedPrice(Decimal(350), currency="RUB"))
    assert split_trailing_price("Caesar Salad $12.50") == (
        "Caesar Salad",
        ParsedPrice(Decimal("12.50"), currency="USD"),
    )
    assert split_trailing_price("Пицца 30 см — 8 кусочков") is None
    assert split_trailing_price("Порция 250 г") is None
    assert split_trailing_price("350 ₽") is None
