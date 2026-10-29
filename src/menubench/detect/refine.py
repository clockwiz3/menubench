"""Pixel-exact price boxes from approximate model boxes.

Vision-language models know roughly where a price is, but their boxes drift by a glyph or half a line. This step
looks at the pixels around the model's box: separates ink from background in the text line, splits the line into
words by the gaps between them, keeps the words the model's box points at (as many as the printed price has),
and shrinks the box to their ink. It is deterministic, free, and falls back to the model's box whenever the result
looks implausible.

Used where people look at boxes (demo, pre-labelling). The benchmark keeps raw boxes: its ground truth is the
typographic line box, taller than the ink, so snapping to ink lowers IoU there without changing any decision.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from menubench.schema import BBox, PricePrediction


def _otsu(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=64, range=(0, 255))
    total = hist.sum()
    if total == 0:
        return 255.0
    centers = (edges[:-1] + edges[1:]) / 2
    weight_bg = np.cumsum(hist)
    weight_fg = total - weight_bg
    mean_cum = np.cumsum(hist * centers)
    mean_all = mean_cum[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mean_all * weight_bg - total * mean_cum) ** 2 / (weight_bg * weight_fg)
    between = np.nan_to_num(between)
    return float(centers[int(np.argmax(between))])


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) of consecutive True values."""
    out = []
    start = None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i))
            start = None
    if start is not None:
        out.append((start, len(mask)))
    return out


def refine_box(image: np.ndarray, box: BBox, words_expected: int | None = None) -> BBox | None:
    """`image` is an RGB array. Returns the refined box, or None to keep the model's box."""
    height, width = image.shape[:2]
    x0, x1 = box.x0 * width, box.x1 * width
    y0, y1 = box.y0 * height, box.y1 * height
    h = max(y1 - y0, 4.0)
    bx0, bx1 = int(max(0, x0 - 2.5 * h)), int(min(width, x1 + 2.5 * h))
    by0, by1 = int(max(0, y0 - 0.6 * h)), int(min(height, y1 + 0.6 * h))
    if bx1 - bx0 < 4 or by1 - by0 < 4:
        return None
    band = image[by0:by1, bx0:bx1].astype(np.float64)

    # Background is what dominates the band's border; ink is whatever differs from it, light or dark.
    border = np.concatenate([band[0], band[-1], band[:, 0], band[:, -1]])
    background = np.median(border, axis=0)
    distance = np.sqrt(((band - background) ** 2).sum(axis=2)) / np.sqrt(3)
    ink = distance > max(_otsu(distance.ravel()), 35.0)

    # The text line: rows with ink under the model's box, the run that contains the box's middle.
    cx0, cx1 = int(x0 - bx0), int(x1 - bx0)
    rows = ink[:, max(cx0, 0) : max(cx1, cx0 + 1)].sum(axis=1) > 0
    middle = int((y0 + y1) / 2 - by0)
    line = next(((a, b) for a, b in _runs(rows) if a <= middle < b), None)
    if line is None:
        return None
    ly0, ly1 = line
    line_h = ly1 - ly0
    if line_h < 0.4 * h or line_h > 2.2 * h:
        return None

    # Keep only ink of the price's own color: menus print weights, volumes and old prices in a paler or different
    # tone right next to the price, and the gap between them is often just one space.
    inside = ink[ly0:ly1, max(cx0, 0) : max(cx1, cx0 + 1)]
    if inside.any():
        target = np.median(band[ly0:ly1, max(cx0, 0) : max(cx1, cx0 + 1)][inside], axis=0)
        contrast = np.sqrt(((target - background) ** 2).sum())
        if contrast > 60:
            same_color = np.sqrt(((band - target) ** 2).sum(axis=2)) < 0.4 * contrast
            ink = ink & same_color

    # Words: columns with ink in the line, glued across gaps narrower than ~a space at this text size.
    # A column counts as ink only with a real stroke in it; anti-aliased specks of a neighbour do not.
    cols = ink[ly0:ly1].sum(axis=0) >= max(1, 0.15 * line_h)
    pieces = _runs(cols)
    if not pieces:
        return None
    words: list[list[int]] = [list(pieces[0])]
    for a, b in pieces[1:]:
        if a - words[-1][1] < max(2, 0.35 * line_h):
            words[-1][1] = b
        else:
            words.append([a, b])

    def overlap(word: list[int]) -> float:
        return max(0.0, min(word[1], cx1) - max(word[0], cx0)) / max(word[1] - word[0], 1)

    picked = [i for i, w in enumerate(words) if overlap(w) >= 0.25]
    if not picked:
        return None
    span = list(range(picked[0], picked[-1] + 1))
    # The model's box may cover only part of the price ("р." without "170"): grow towards the closest neighbour
    # on the line until the printed price's word count is reached, as long as the neighbour is right next to it.
    while words_expected and len(span) < words_expected:
        left = span[0] - 1 if span[0] > 0 else None
        right = span[-1] + 1 if span[-1] + 1 < len(words) else None
        gaps = []
        if left is not None:
            gaps.append((words[span[0]][0] - words[left][1], left))
        if right is not None:
            gaps.append((words[right][0] - words[span[-1]][1], right))
        if not gaps:
            break
        gap, nxt = min(gaps)
        if gap > 0.8 * line_h:
            break
        span = sorted([*span, nxt])
    if words_expected and len(span) > words_expected:
        best = max(
            range(len(span) - words_expected + 1),
            key=lambda s: sum(overlap(words[i]) for i in span[s : s + words_expected]),
        )
        span = span[best : best + words_expected]
    wx0, wx1 = words[span[0]][0], words[span[-1]][1]
    # Small marks right next to the price ("р." keeps its dot) are part of it; anything across a space is not.
    any_ink = ink[ly0:ly1].any(axis=0)
    reach = max(2, int(0.15 * line_h))
    while True:  # rightwards: next ink column within reach of the current right edge
        ahead = np.flatnonzero(any_ink[wx1 : wx1 + reach])
        if ahead.size == 0:
            break
        wx1 += int(ahead[0]) + 1
    while wx0 > 0:  # leftwards, symmetric
        lo = max(0, wx0 - reach)
        behind = np.flatnonzero(any_ink[lo:wx0])
        if behind.size == 0:
            break
        wx0 = lo + int(behind[-1])
    tight_rows = np.where(ink[:, wx0:wx1].sum(axis=1) > 0)[0]
    tight_rows = tight_rows[(tight_rows >= ly0 - 1) & (tight_rows <= ly1)]
    if tight_rows.size == 0:
        return None
    ty0, ty1 = int(tight_rows[0]), int(tight_rows[-1]) + 1

    refined = BBox(
        x0=(bx0 + wx0) / width,
        y0=(by0 + ty0) / height,
        x1=min(1.0, (bx0 + wx1) / width),
        y1=min(1.0, (by0 + ty1) / height),
    )
    # Plausibility: same place, similar size. Otherwise the model's box was better than our guess.
    grew = (refined.x1 - refined.x0) > (box.x1 - box.x0) * 2.5 + 2 * h / width
    if refined.iou(box) < 0.15 or grew:
        return None
    return refined


def refine_prices(pages: list[Image.Image], prices: tuple[PricePrediction, ...]) -> tuple[PricePrediction, ...]:
    arrays = [np.asarray(p.convert("RGB")) for p in pages]
    out = []
    for price in prices:
        if price.bbox is None or price.page >= len(arrays):
            out.append(price)
            continue
        words = len(price.text.split()) if price.text else None
        refined = refine_box(arrays[price.page], price.bbox, words)
        out.append(price.model_copy(update={"bbox": refined}) if refined else price)
    return tuple(out)
