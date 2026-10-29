"""Turns a pipeline prediction into an annotation draft that a person then corrects."""

from __future__ import annotations

from menubench.eval.text import cer, normalize
from menubench.schema import BBox, MenuAnnotation, MenuItem, MenuPrediction, PriceAnnotation, PriceKind, TextLine


def _name_box(name: str, price: BBox, page: int, lines: tuple[TextLine, ...]) -> BBox:
    """The OCR line that reads like the name and sits nearest to the price; a placeholder box otherwise."""
    target = normalize(name)
    hits = [
        ln
        for ln in lines
        if ln.page == page
        and (normalize(ln.text) == target or cer(ln.text, name) <= 0.2 or target in normalize(ln.text))
    ]
    if hits:
        cy = (price.y0 + price.y1) / 2
        return min(hits, key=lambda ln: abs((ln.bbox.y0 + ln.bbox.y1) / 2 - cy) + abs(ln.bbox.x1 - price.x0) * 0.3).bbox
    width = 0.25
    x0 = max(0.0, price.x0 - width - 0.01)
    return BBox(x0=x0, y0=price.y0, x1=max(x0 + 0.01, price.x0 - 0.01), y1=price.y1)


def prediction_to_draft(base: MenuAnnotation, prediction: MenuPrediction) -> MenuAnnotation:
    items: list[MenuItem] = []
    by_name: dict[tuple[int, str], str] = {}
    prices: list[PriceAnnotation] = []
    for n, p in enumerate(prediction.prices, start=1):
        if p.bbox is None:
            continue
        item_ids: tuple[str, ...] = ()
        if p.name:
            key = (p.page, normalize(p.name))
            if key not in by_name:
                item_id = f"i{len(items) + 1}"
                by_name[key] = item_id
                items.append(
                    MenuItem(
                        id=item_id, page=p.page, name=p.name, bbox=_name_box(p.name, p.bbox, p.page, prediction.lines)
                    )
                )
            item_ids = (by_name[key],)
        kind = p.kind if p.kind is not PriceKind.RANGE or p.value_max is not None else PriceKind.SINGLE
        prices.append(
            PriceAnnotation(
                id=f"p{n}",
                page=p.page,
                value=p.value,
                value_max=p.value_max if kind is PriceKind.RANGE else None,
                currency=p.currency,
                kind=kind,
                bbox=p.bbox,
                item_ids=item_ids,
            )
        )
    return base.model_copy(update={"items": tuple(items), "prices": tuple(prices)})
