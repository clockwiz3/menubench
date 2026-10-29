import random
from decimal import Decimal

import pytest

from menubench.schema import PriceKind, TextRole
from menubench.synth.content import RU_STYLES, ContentOptions, PriceStyle, generate_content
from menubench.synth.generate import TEMPLATES, TEST_ONLY_TEMPLATES, V1_CONTENT, SynthConfig, build_menu, plan_menus


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


def test_plan_is_stable_and_holds_out_templates() -> None:
    cfg = SynthConfig(n=80, seed=5)
    plan = list(plan_menus(cfg))
    assert plan == list(plan_menus(cfg))
    assert {p.split for p in plan} == {"dev", "test"}
    assert {p.template for p in plan} == set(TEMPLATES)
    assert not {p.template for p in plan if p.split == "dev"} & set(TEST_ONLY_TEMPLATES)
    assert len({p.augment for p in plan}) == 3


@pytest.mark.render
@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_rendered_menu_has_exact_ground_truth(template: str) -> None:
    from menubench.synth.render import Renderer

    try:
        renderer = Renderer().__enter__()
    except Exception as exc:  # Chromium is not installed
        pytest.skip(f"playwright browser unavailable: {exc}")
    try:
        menu = build_menu(renderer, "m", seed=11, lang="ru", template=template, with_catalog=True, **V1_CONTENT)
    finally:
        renderer.__exit__(None, None, None)
    ann = menu.annotation
    assert ann.prices and ann.items
    price_lines = [line for line in ann.lines if line.role is TextRole.PRICE]
    assert len(price_lines) == len(ann.prices)
    assert ann.catalog and any(i.catalog_id for i in ann.items)
    for price in ann.prices:
        assert any(price.bbox.iou(line.bbox) > 0.99 for line in price_lines)
    assert menu.png.startswith(b"\x89PNG")


@pytest.mark.render
@pytest.mark.parametrize("level", ["scan", "photo"])
def test_augmented_boxes_still_cover_the_prices(level: str) -> None:
    """After warping, every price box must still contain ink, not empty background."""
    import io

    import numpy as np
    from PIL import Image

    from menubench.schema import AugmentLevel
    from menubench.synth.render import Renderer

    try:
        renderer = Renderer().__enter__()
    except Exception as exc:
        pytest.skip(f"playwright browser unavailable: {exc}")
    try:
        menu = build_menu(
            renderer, "m", seed=3, lang="en", template="classic_columns", augment_level=AugmentLevel(level)
        )
    finally:
        renderer.__exit__(None, None, None)
    assert menu.ext == "jpg" and menu.annotation.augment == AugmentLevel(level)
    img = np.asarray(Image.open(io.BytesIO(menu.png)).convert("L"), dtype=float)
    h, w = img.shape
    for price in menu.annotation.prices:
        b = price.bbox
        patch = img[int(b.y0 * h) : int(b.y1 * h) + 1, int(b.x0 * w) : int(b.x1 * w) + 1]
        assert patch.size and patch.std() > 8, f"box {price.id} looks empty after {level} augmentation"


def test_catalog_has_traps_and_absent_items() -> None:
    from menubench.synth.catalog import make_catalog, translit

    content, _ = generate_content(random.Random(9), ContentOptions(lang="ru", min_items=5, max_items=6))
    catalog, mapping = make_catalog(content, random.Random(1), absent_rate=0.3)
    linked = {cid for cid in mapping.values() if cid}
    assert len(catalog) > len(linked)  # distractors present
    assert None in mapping.values()  # some items missing from the till
    assert {c.id for c in catalog} >= linked
    assert translit("Щи") == "Schi"


def test_hard_cases_render_as_expected_text() -> None:
    content, _ = generate_content(
        random.Random(2),
        ContentOptions(lang="ru", venue="cafe", hard_cases={"crossed": 0.4, "from": 0.3, "range": 0.3}),
    )
    kinds = {p.kind for item in content.items() for p in item.prices}
    assert PriceKind.FROM in kinds or PriceKind.RANGE in kinds
    for item in content.items():
        for p in item.prices:
            if p.kind is PriceKind.FROM:
                assert p.text.startswith("от ")
            if p.kind is PriceKind.RANGE:
                assert "–" in p.text and p.value_max and p.value_max > p.value
        if item.old_price:
            assert item.old_price.value > item.prices[0].value
