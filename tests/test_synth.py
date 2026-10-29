import random
from decimal import Decimal

import pytest

from menubench.schema import PriceKind, TextRole
from menubench.synth.content import RU_STYLES, ContentOptions, PriceStyle, generate_content
from menubench.synth.generate import TEMPLATES, SynthConfig, build_menu, plan_menus


def test_content_is_deterministic() -> None:
    a, _ = generate_content(random.Random(7), ContentOptions(lang="ru"))
    b, _ = generate_content(random.Random(7), ContentOptions(lang="ru"))
    assert a == b
    assert a.sections and all(section.items for section in a.sections)


def test_sized_sections_have_increasing_prices() -> None:
    content, _ = generate_content(random.Random(3), ContentOptions(lang="en", venue="coffee"))
    sized = [item for section in content.sections if section.sizes for item in section.items]
    assert sized
    for item in sized:
        values = [p.value for p in item.prices]
        assert values == sorted(values) and len(set(values)) == len(values)
        assert all(p.kind is PriceKind.SIZE_VARIANT for p in item.prices)


@pytest.mark.parametrize(
    ("style", "value", "expected"),
    [
        (RU_STYLES[0], Decimal(1150), "1 150 ₽"),
        (RU_STYLES[5], Decimal(350), "350,-"),
        (PriceStyle("usd", "USD", True, True, "${v}"), Decimal("12.5"), "$12.50"),
        (PriceStyle("eur", "EUR", True, True, "{v} €", decimal_sep=","), Decimal("4.25"), "4,25 €"),
    ],
)
def test_price_style_format(style: PriceStyle, value: Decimal, expected: str) -> None:
    assert style.format(value) == expected


def test_plan_is_stable_and_split() -> None:
    cfg = SynthConfig(n=40, seed=5)
    plan = list(plan_menus(cfg))
    assert plan == list(plan_menus(cfg))
    assert {split for *_, split in plan} == {"dev", "test"}
    assert {template for *_, template, _ in plan} == set(TEMPLATES)


@pytest.mark.render
@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_rendered_menu_has_exact_ground_truth(template: str) -> None:
    from menubench.synth.render import Renderer

    try:
        renderer = Renderer().__enter__()
    except Exception as exc:  # Chromium is not installed
        pytest.skip(f"playwright browser unavailable: {exc}")
    try:
        menu = build_menu(renderer, "m", seed=11, lang="ru", template=template)
    finally:
        renderer.__exit__(None, None, None)
    ann = menu.annotation
    assert ann.prices and ann.items
    price_lines = [line for line in ann.lines if line.role is TextRole.PRICE]
    assert len(price_lines) == len(ann.prices)
    for price in ann.prices:
        assert any(price.bbox.iou(line.bbox) > 0.99 for line in price_lines)
    assert menu.png.startswith(b"\x89PNG")
