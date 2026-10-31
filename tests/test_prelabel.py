"""Draft building from a prediction: OCR boxes that do not fit their text, repeated names, lone size variants."""

from __future__ import annotations

from decimal import Decimal

from menubench.pipeline.prelabel import prediction_to_draft
from menubench.schema import (
    BBox,
    MenuAnnotation,
    MenuPrediction,
    Page,
    PriceKind,
    PricePrediction,
    Source,
    TextLine,
)

BASE = MenuAnnotation(
    menu_id="m", source=Source.REAL, lang="sr", pages=(Page(index=0, width=1000, height=1000, image="m/page-0.jpg"),)
)


def box(x0: float, y0: float, x1: float, y1: float) -> BBox:
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1)


def price(value: int, b: BBox, name: str, kind: PriceKind = PriceKind.SINGLE) -> PricePrediction:
    return PricePrediction(page=0, value=Decimal(value), bbox=b, name=name, kind=kind, confidence=0.9)


def line(text: str, b: BBox) -> TextLine:
    return TextLine(page=0, text=text, bbox=b)


# 0.01 of the page per character, as on most of the real photos.
def text_box(text: str, x0: float, y0: float) -> BBox:
    return box(x0, y0, x0 + 0.01 * len(text), y0 + 0.015)


def test_same_name_in_two_columns_is_two_items() -> None:
    left, right = text_box("Kajmak", 0.1, 0.5), text_box("Kajmak", 0.6, 0.5)
    pred = MenuPrediction(
        menu_id="m",
        config="c",
        prices=(price(2, box(0.35, 0.5, 0.42, 0.515), "Kajmak"), price(2, box(0.85, 0.5, 0.92, 0.515), "Kajmak")),
        lines=(line("Kajmak", left), line("Kajmak", right)),
    )
    draft = prediction_to_draft(BASE, pred)
    assert [it.bbox for it in draft.items] == [left, right]
    assert [p.item_ids for p in draft.prices] == [("i1",), ("i2",)]


def test_box_too_narrow_for_its_text_moves_to_the_names_column() -> None:
    name = "Pohovani luk sa tartar sosom"
    pred = MenuPrediction(
        menu_id="m",
        config="c",
        prices=(price(340, box(0.86, 0.66, 0.94, 0.675), name),),
        lines=(
            line("Pohovane lignje sa tartar sosom", text_box("Pohovane lignje sa tartar sosom", 0.1, 0.7)),
            line("Fried onion rings and Tartar sauce", text_box("Fried onion rings and Tartar sauce", 0.1, 0.68)),
            line("130g", text_box("130g", 0.75, 0.66)),
            # The OCR model paired the name with the allergen marks' box.
            line(name, box(0.49, 0.657, 0.55, 0.674)),
        ),
    )
    item = prediction_to_draft(BASE, pred).items[0]
    assert item.bbox.x0 == 0.1  # the column's left edge, not the weight's
    assert item.bbox.x1 < 0.86  # stops before the price


def test_name_box_stops_before_its_price() -> None:
    pred = MenuPrediction(
        menu_id="m",
        config="c",
        prices=(price(12, box(0.5, 0.8, 0.6, 0.815), "Kocka burger"),),
        # Leader dots and the price itself ended up in the line's box.
        lines=(line("Kocka burger", box(0.1, 0.8, 0.62, 0.815)),),
    )
    assert prediction_to_draft(BASE, pred).items[0].bbox.x1 < 0.5


def test_lone_size_variant_becomes_a_single_price() -> None:
    pred = MenuPrediction(
        menu_id="m",
        config="c",
        prices=(
            price(150, box(0.8, 0.2, 0.9, 0.215), "Riba pečena u soli", PriceKind.SIZE_VARIANT),
            price(250, box(0.8, 0.4, 0.9, 0.415), "Pivo", PriceKind.SIZE_VARIANT),
            price(350, box(0.8, 0.42, 0.9, 0.435), "Pivo", PriceKind.SIZE_VARIANT),
        ),
        lines=(
            line("Riba pečena u soli", text_box("Riba pečena u soli", 0.1, 0.2)),
            line("Pivo", text_box("Pivo", 0.1, 0.41)),
        ),
    )
    assert [p.kind for p in prediction_to_draft(BASE, pred).prices] == [
        PriceKind.SINGLE,
        PriceKind.SIZE_VARIANT,
        PriceKind.SIZE_VARIANT,
    ]
