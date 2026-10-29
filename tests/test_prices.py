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


def test_merged_size_label_is_not_a_name() -> None:
    from menubench.detect import find_candidates
    from menubench.schema import BBox, TextLine

    box = BBox(x0=0.1, y0=0.1, x1=0.5, y1=0.12)
    cands = find_candidates(
        [TextLine(page=0, text="25 см 1 150 р.", bbox=box), TextLine(page=0, text="Борщ 350 ₽", bbox=box)]
    )
    assert [c.merged_name for c in cands] == [None, "Борщ"]
    assert cands[0].parsed.value == 1150


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ('12" $29', ["29"]),
        ("S 5,75 € M 7,95 € L 8,50 €", ["5.75", "7.95", "8.50"]),
        ("Борщ ........ 350", ["350"]),
        ("Борщ · 250 г 350 ₽", ["350"]),
        ("Пицца 30 см — 8 кусочков", []),
        ("Комплексный обед с 12:00 до 15:00", []),
        ("Салат с тунцом 2 шт", []),
        ("от 300 ₽ Греческий", ["300"]),
        ("450 ₽ 350 ₽", ["450", "350"]),
    ],
)
def test_find_prices_inside_lines(text: str, values: list[str]) -> None:
    from menubench.prices import find_prices

    assert [p.value for _, _, p in find_prices(text)] == [Decimal(v) for v in values]


def test_phone_numbers_are_not_prices() -> None:
    from menubench.prices import find_prices

    assert find_prices("Тел. 8 800 555-35-35") == []
    assert find_prices("Call (555) 214-7788") == []
