"""Menu content: venue, sections, items and prices, generated deterministically from a seed."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from menubench.schema import PriceKind
from menubench.synth.lexicon import VOCAB, SectionVocab


@dataclass
class PriceSpec:
    id: str
    value: Decimal
    kind: PriceKind = PriceKind.SINGLE
    value_max: Decimal | None = None
    size_label: str | None = None
    text: str = ""  # formatted as printed on the menu
    old_text: str | None = None  # CROSSED companion: the struck-through old price is a separate PriceSpec


@dataclass
class ItemSpec:
    id: str
    name: str
    description: str | None
    prices: list[PriceSpec]
    weight: str | None = None  # "250 г": a number that is not a price


@dataclass
class SectionSpec:
    title: str
    items: list[ItemSpec]
    sizes: tuple[str, ...] = ()  # shared size labels when every item in the section is sized


@dataclass
class MenuContent:
    lang: str
    venue: str
    title: str
    currency: str | None
    sections: list[SectionSpec]
    notes: list[str] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)

    def items(self) -> list[ItemSpec]:
        return [item for section in self.sections for item in section.items]


@dataclass(frozen=True)
class PriceStyle:
    """How prices are printed on one menu. A menu keeps one style throughout, like real menus do."""

    name: str
    currency: str
    show_currency: bool
    decimals: bool
    pattern: str  # {v} is replaced by the formatted number
    decimal_sep: str = "."
    thousands_sep: str = ""

    def format(self, value: Decimal) -> str:
        if self.decimals:
            number = f"{value:.2f}"
        else:
            number = f"{value.quantize(Decimal('1'), ROUND_HALF_UP)}"
        whole, _, frac = number.partition(".")
        if self.thousands_sep and len(whole) > 3:
            whole = f"{int(whole):,}".replace(",", self.thousands_sep)
        number = whole + (self.decimal_sep + frac if frac else "")
        return self.pattern.replace("{v}", number)


RU_STYLES = (
    PriceStyle("rub-sign", "RUB", True, False, "{v} ₽", thousands_sep=" "),
    PriceStyle("rub-sign-tight", "RUB", True, False, "{v}₽"),
    PriceStyle("rub-r", "RUB", True, False, "{v} р.", thousands_sep=" "),
    PriceStyle("rub-rub", "RUB", True, False, "{v} руб."),
    PriceStyle("rub-bare", "RUB", False, False, "{v}"),
    PriceStyle("rub-dash", "RUB", False, False, "{v},-"),
)
EN_STYLES = (
    PriceStyle("usd-sign", "USD", True, True, "${v}"),
    PriceStyle("usd-bare", "USD", False, True, "{v}"),
    PriceStyle("usd-sign-short", "USD", True, False, "${v}"),
    PriceStyle("eur-prefix", "EUR", True, True, "€{v}"),
    PriceStyle("eur-suffix", "EUR", True, True, "{v} €", decimal_sep=","),
)
STYLES = {"ru": RU_STYLES, "en": EN_STYLES}


def _round_price(raw: float, style: PriceStyle, rng: random.Random) -> Decimal:
    if style.currency == "RUB":
        step = 10 if raw < 1000 else 50
        value = max(step, round(raw / step) * step)
        if rng.random() < 0.15:
            value -= 1  # 349, 499: common retail pricing
        return Decimal(value)
    if not style.decimals:
        return Decimal(max(1, round(raw)))
    cents = rng.choice((0, 0, 50, 95, 25, 75))
    return Decimal(int(raw)) + Decimal(cents) / 100 if raw >= 1 else Decimal("0.95")


@dataclass
class ContentOptions:
    lang: str
    venue: str | None = None
    min_sections: int = 3
    max_sections: int = 4
    min_items: int = 3
    max_items: int = 6
    description_rate: float = 0.5
    weight_rate: float = 0.0
    hard_cases: dict[str, float] = field(default_factory=dict)  # tag -> probability per eligible item


def generate_content(rng: random.Random, opts: ContentOptions) -> tuple[MenuContent, PriceStyle]:
    sections_vocab, venues = VOCAB[opts.lang]
    venue_key = opts.venue or rng.choice(sorted(venues))
    venue = venues[venue_key]
    style = rng.choice(STYLES[opts.lang])
    if venue_key == "canteen" and style.currency == "EUR":
        style = STYLES[opts.lang][0]

    n_sections = min(len(venue.sections), rng.randint(opts.min_sections, opts.max_sections))
    keys = list(venue.sections[:n_sections])
    content = MenuContent(
        lang=opts.lang,
        venue=venue_key,
        title=rng.choice(venue.titles),
        currency=style.currency if style.show_currency else None,
        sections=[],
        notes=rng.sample(list(venue.notes), k=min(len(venue.notes), rng.randint(0, 2))),
    )
    if content.notes:
        content.tags.add("distractor_note")

    counter = 0
    for key in keys:
        vocab = sections_vocab[key]
        sizes = rng.choice(vocab.sizes) if vocab.sizes else ()
        section = SectionSpec(title=vocab.title, items=[], sizes=sizes)
        used: set[str] = set()
        for _ in range(rng.randint(opts.min_items, opts.max_items)):
            name = _item_name(rng, vocab, used)
            if name is None:
                break
            counter += 1
            item_id = f"i{counter}"
            item = ItemSpec(
                id=item_id,
                name=name,
                description=_description(rng, vocab) if rng.random() < opts.description_rate else None,
                prices=_prices(rng, item_id, venue.band, vocab, sizes, style),
            )
            if opts.weight_rate and rng.random() < opts.weight_rate and not sizes:
                item.weight = _weight(rng, opts.lang)
                content.tags.add("weight")
            section.items.append(item)
        if section.items:
            content.sections.append(section)
            if sizes:
                content.tags.add("size_variant")
    return content, style


def _item_name(rng: random.Random, vocab: SectionVocab, used_bases: set[str]) -> str | None:
    free = [b for b in vocab.bases if b not in used_bases]
    if not free:
        return None
    base = rng.choice(free)
    used_bases.add(base)
    return f"{base} {rng.choice(vocab.modifiers)}" if vocab.modifiers and rng.random() < 0.4 else base


def _description(rng: random.Random, vocab: SectionVocab) -> str | None:
    if not vocab.ingredients:
        return None
    parts = rng.sample(vocab.ingredients, k=min(len(vocab.ingredients), rng.randint(2, 3)))
    return ", ".join(parts)


def _weight(rng: random.Random, lang: str) -> str:
    if lang == "ru":
        return f"{rng.choice((150, 200, 250, 300, 350))} г"
    return f"{rng.choice((6, 8, 10, 12))} oz"


def _prices(
    rng: random.Random,
    item_id: str,
    band: tuple[float, float],
    vocab: SectionVocab,
    sizes: tuple[str, ...],
    style: PriceStyle,
) -> list[PriceSpec]:
    base = rng.uniform(*band) * vocab.price_factor
    if not sizes:
        value = _round_price(base, style, rng)
        return [PriceSpec(id=f"{item_id}p1", value=value, text=style.format(value))]
    prices: list[PriceSpec] = []
    previous = Decimal(0)
    for n, label in enumerate(sizes, start=1):
        value = _round_price(base * (1 + 0.3 * (n - 1)), style, rng)
        if value <= previous:
            value = previous + (Decimal(10) if style.currency == "RUB" else Decimal("0.5"))
        previous = value
        prices.append(
            PriceSpec(
                id=f"{item_id}p{n}",
                value=value,
                kind=PriceKind.SIZE_VARIANT,
                size_label=label,
                text=style.format(value),
            )
        )
    return prices
