"""Turns a pipeline prediction into an annotation draft that a person then corrects."""

from __future__ import annotations

from menubench.eval.text import cer, normalize
from menubench.schema import BBox, MenuAnnotation, MenuItem, MenuPrediction, PriceAnnotation, PriceKind, TextLine

# OCR models sometimes pair a line's text with a neighbour's box, most often on angled photos. A box whose width
# is far from what its text needs, or that sits on a price, is rebuilt from the row and the column's left edge.
MIN_WIDTH_SHARE = 0.45
MAX_WIDTH_SHARE = 2.5
GAP = 0.005


def _box(x0: float, y0: float, x1: float, y1: float) -> BBox:
    x0, x1 = min(max(x0, 0.0), 0.99), min(max(x1, 0.0), 1.0)
    return BBox(x0=x0, y0=y0, x1=max(x1, x0 + 0.01), y1=y1)


def _char_width(page: int, lines: tuple[TextLine, ...]) -> float | None:
    """Median width of one character on the page, from lines long enough to average out."""
    widths = sorted((ln.bbox.x1 - ln.bbox.x0) / len(ln.text) for ln in lines if ln.page == page and len(ln.text) >= 8)
    return widths[len(widths) // 2] if widths else None


def _width_share(line: TextLine, char_width: float) -> float:
    return (line.bbox.x1 - line.bbox.x0) / (char_width * max(len(line.text), 1))


def _on_price(box: BBox, prices: list[BBox]) -> bool:
    area = max((box.x1 - box.x0) * (box.y1 - box.y0), 1e-9)
    for p in prices:
        w = min(box.x1, p.x1) - max(box.x0, p.x0)
        h = min(box.y1, p.y1) - max(box.y0, p.y0)
        if w > 0 and h > 0 and w * h / area > 0.4:
            return True
    return False


def _same_row(a: BBox, b: BBox) -> bool:
    return min(a.y1, b.y1) - max(a.y0, b.y0) > 0.3 * min(a.y1 - a.y0, b.y1 - b.y0)


def _left_edge(
    line: TextLine, char_width: float, price: BBox, lines: tuple[TextLine, ...], prices: list[BBox]
) -> float | None:
    """Where the names' column starts near this row: the leftmost believable line between the previous column's
    prices and this price. Weights, leaders and size notes sit further right, so they never win."""
    cy = (line.bbox.y0 + line.bbox.y1) / 2
    h = line.bbox.y1 - line.bbox.y0
    boundary = max(
        (p.x1 for p in prices if p.x1 < price.x0 - 0.02 and abs((p.y0 + p.y1) / 2 - cy) <= 6 * h), default=0.0
    )
    starts = [
        ln.bbox.x0
        for ln in lines
        if ln.page == line.page
        and ln is not line
        and boundary <= ln.bbox.x0 < price.x0 - 0.02
        and abs((ln.bbox.y0 + ln.bbox.y1) / 2 - cy) <= 4 * h
        and MIN_WIDTH_SHARE <= _width_share(ln, char_width) <= MAX_WIDTH_SHARE
    ]
    return min(starts) if starts else None


def _fit(line: TextLine, price: BBox, lines: tuple[TextLine, ...], prices: list[BBox]) -> BBox:
    box = line.bbox
    char_width = _char_width(line.page, lines)
    if char_width is not None:
        share = _width_share(line, char_width)
        expected = char_width * len(line.text)
        if share < MIN_WIDTH_SHARE or _on_price(box, prices):
            left = _left_edge(line, char_width, price, lines, prices)
            if left is not None:
                box = _box(left, box.y0, left + expected, box.y1)
        elif share > MAX_WIDTH_SHARE:
            box = _box(box.x0, box.y0, box.x0 + expected * 1.15, box.y1)
    # A name never runs into its own price: dot leaders and the price stay outside.
    if _same_row(box, price) and box.x0 < price.x0 - 0.01 < box.x1:
        box = _box(box.x0, box.y0, price.x0 - GAP, box.y1)
    return box


def _name_box(name: str, price: BBox, page: int, lines: tuple[TextLine, ...], prices: list[BBox] | None = None) -> BBox:
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
        line = min(hits, key=lambda ln: abs((ln.bbox.y0 + ln.bbox.y1) / 2 - cy) + abs(ln.bbox.x1 - price.x0) * 0.3)
        return _fit(line, price, lines, prices or [])
    width = 0.25
    x0 = max(0.0, price.x0 - width - 0.01)
    return BBox(x0=x0, y0=price.y0, x1=max(x0 + 0.01, price.x0 - 0.01), y1=price.y1)


def prediction_to_draft(base: MenuAnnotation, prediction: MenuPrediction) -> MenuAnnotation:
    items: list[MenuItem] = []
    prices: list[PriceAnnotation] = []
    price_boxes: dict[int, list[BBox]] = {}
    for p in prediction.prices:
        if p.bbox is not None:
            price_boxes.setdefault(p.page, []).append(p.bbox)
    for n, p in enumerate(prediction.prices, start=1):
        if p.bbox is None:
            continue
        item_ids: tuple[str, ...] = ()
        if p.name:
            box = _name_box(p.name, p.bbox, p.page, prediction.lines, price_boxes.get(p.page, []))
            # Same name and the same place is one item with several prices; the same name elsewhere on the page
            # (a second column, a translated half) is its own item.
            same = next(
                (
                    it
                    for it in items
                    if it.page == p.page and normalize(it.name) == normalize(p.name) and it.bbox.iou(box) > 0.5
                ),
                None,
            )
            if same is None:
                same = MenuItem(id=f"i{len(items) + 1}", page=p.page, name=p.name, bbox=box)
                items.append(same)
            item_ids = (same.id,)
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
    # A size variant needs a sibling: a lone price next to a weight ("1000 g") is just the price.
    per_item: dict[str, int] = {}
    for pr in prices:
        for item_id in pr.item_ids:
            per_item[item_id] = per_item.get(item_id, 0) + 1
    prices = [
        pr.model_copy(update={"kind": PriceKind.SINGLE})
        if pr.kind is PriceKind.SIZE_VARIANT and all(per_item.get(i, 0) < 2 for i in pr.item_ids)
        else pr
        for pr in prices
    ]
    return base.model_copy(update={"items": tuple(items), "prices": tuple(prices)})
