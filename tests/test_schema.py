from decimal import Decimal

import pytest
from pydantic import ValidationError

from menubench.schema import (
    BBox,
    CatalogEntry,
    LinkCandidate,
    LinkDecision,
    MenuAnnotation,
    MenuItem,
    Page,
    PriceAnnotation,
    PriceKind,
    Source,
)

PAGE = Page(index=0, width=1000, height=1400, image="menu-0001/page-0.png")


def _item(item_id: str = "i1", catalog_id: str | None = None) -> MenuItem:
    return MenuItem(id=item_id, page=0, name="Борщ", bbox=BBox(x0=0.1, y0=0.1, x1=0.5, y1=0.13), catalog_id=catalog_id)


def _price(**overrides: object) -> PriceAnnotation:
    fields: dict[str, object] = {
        "id": "p1",
        "page": 0,
        "value": Decimal("350"),
        "currency": "RUB",
        "bbox": BBox(x0=0.8, y0=0.1, x1=0.9, y1=0.13),
        "item_ids": ("i1",),
    }
    fields.update(overrides)
    return PriceAnnotation.model_validate(fields)


def test_bbox_iou() -> None:
    a = BBox(x0=0, y0=0, x1=0.5, y1=0.5)
    b = BBox(x0=0.25, y0=0, x1=0.75, y1=0.5)
    assert a.iou(a) == pytest.approx(1.0)
    assert a.iou(b) == pytest.approx(1 / 3)
    assert a.iou(BBox(x0=0.6, y0=0.6, x1=0.9, y1=0.9)) == 0.0


def test_bbox_rejects_inverted() -> None:
    with pytest.raises(ValidationError):
        BBox(x0=0.5, y0=0, x1=0.4, y1=0.1)


def test_range_requires_upper_bound() -> None:
    with pytest.raises(ValidationError):
        _price(kind=PriceKind.RANGE)
    with pytest.raises(ValidationError):
        _price(value_max=Decimal("400"))
    assert _price(kind=PriceKind.RANGE, value_max=Decimal("450")).value_max == Decimal("450")


def test_annotation_roundtrip() -> None:
    menu = MenuAnnotation(
        menu_id="menu-0001",
        source=Source.SYNTHETIC,
        lang="ru",
        pages=(PAGE,),
        items=(_item(catalog_id="c1"),),
        prices=(_price(),),
        catalog=(CatalogEntry(id="c1", name="БОРЩ УКР."),),
        seed=42,
    )
    assert MenuAnnotation.model_validate_json(menu.model_dump_json()) == menu


def test_annotation_rejects_dangling_references() -> None:
    with pytest.raises(ValidationError, match="missing items"):
        MenuAnnotation(menu_id="m", source=Source.SYNTHETIC, lang="ru", pages=(PAGE,), prices=(_price(),))
    with pytest.raises(ValidationError, match="missing catalog entry"):
        MenuAnnotation(
            menu_id="m", source=Source.SYNTHETIC, lang="ru", pages=(PAGE,), items=(_item(catalog_id="nope"),)
        )


def test_link_decision_consistency() -> None:
    LinkDecision(action="link", catalog_id="c1")
    LinkDecision(action="hint", candidates=(LinkCandidate(catalog_id="c1", score=0.7),), reason="two close matches")
    with pytest.raises(ValidationError):
        LinkDecision(action="abstain", catalog_id="c1")
    with pytest.raises(ValidationError):
        LinkDecision(action="hint")
