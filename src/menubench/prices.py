"""Parsing price strings as they are printed on menus.

Only strings that are entirely a price parse; "250 г", "350 мл", "10:00" or a phone number do not.
`split_trailing_price` handles OCR lines where a dish name and its price were merged into one line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from menubench.schema import PriceKind

_SPACES = "    "
_CURRENCY = {
    "₽": "RUB",
    "руб": "RUB",
    "руб.": "RUB",
    "р": "RUB",
    "р.": "RUB",
    "rub": "RUB",
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "₸": "KZT",
    "тг": "KZT",
}
_PRE = r"(?P<pre>[$€£₽₸])?"
_POST = r"(?P<post>₽|руб\.?|р\.?|rub|€|\$|₸|тг|usd|eur)?"
_NUM = r"\d{1,3}(?:[    ]\d{3})+|\d+"
_AMOUNT = rf"(?P<num>{_NUM})(?:[.,](?P<dec>\d{{1,2}}))?(?:,-)?"
_SINGLE = re.compile(rf"^(?P<from>от|from)?\s*{_PRE}\s?{_AMOUNT}\s?{_POST}$", re.IGNORECASE)
_RANGE = re.compile(
    rf"^{_PRE}\s?(?P<a>{_NUM})(?:[.,](?P<ad>\d{{1,2}}))?\s?{_POST}\s*[-–—]\s*"
    rf"(?P<pre2>[$€£₽₸])?\s?(?P<b>{_NUM})(?:[.,](?P<bd>\d{{1,2}}))?\s?(?P<post2>₽|руб\.?|р\.?|€|\$|₸|тг)?$",
    re.IGNORECASE,
)
_TRAILING = re.compile(r"^(?P<head>.*?\S)[\s.·…_-]{1,}(?P<tail>(?:от\s|from\s)?[$€£₽₸]?\s?[\d][\d  .,]*\s?\S{0,4})$")


@dataclass(frozen=True)
class ParsedPrice:
    value: Decimal
    value_max: Decimal | None = None
    kind: PriceKind = PriceKind.SINGLE
    currency: str | None = None


def _number(whole: str, dec: str | None) -> Decimal | None:
    digits = "".join(ch for ch in whole if ch.isdigit())
    try:
        value = Decimal(digits)
        if dec:
            value += Decimal(dec.ljust(2, "0")) / 100
    except InvalidOperation:
        return None
    return value


def _currency(*marks: str | None) -> str | None:
    for mark in marks:
        if mark:
            return _CURRENCY.get(mark.lower())
    return None


def parse_price(text: str) -> ParsedPrice | None:
    s = text.strip().strip("*").strip()
    for ch in _SPACES[:-1]:
        s = s.replace(ch, " ")
    if not s or len(s) > 24:
        return None
    m = _SINGLE.match(s)
    if m:
        value = _number(m["num"], m["dec"])
        currency = _currency(m["pre"], m["post"])
        if value is None or value == 0 or value > 100000:
            return None
        if currency is None and value < 1:  # "0,25" is a cup size, not a price
            return None
        kind = PriceKind.FROM if m["from"] else PriceKind.SINGLE
        return ParsedPrice(value, None, kind, currency)
    m = _RANGE.match(s)
    if m:
        a, b = _number(m["a"], m["ad"]), _number(m["b"], m["bd"])
        if a is None or b is None or not 0 < a < b:
            return None
        return ParsedPrice(a, b, PriceKind.RANGE, _currency(m["pre"], m["post"], m["pre2"], m["post2"]))
    return None


def split_trailing_price(text: str) -> tuple[str, ParsedPrice] | None:
    """'Борщ ........ 350 ₽' -> ('Борщ', 350 RUB). Returns None when the line does not end with a price."""
    m = _TRAILING.match(text.strip())
    if not m:
        return None
    parsed = parse_price(m["tail"])
    head = m["head"].strip(" .·…_-")
    if parsed is None or not head or not any(ch.isalpha() for ch in head):
        return None
    return head, parsed
