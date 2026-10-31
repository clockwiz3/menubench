"""Models report boxes in different conventions. Everything is converted to page-relative 0..1 xyxy."""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from menubench.schema import BBox


class BoxFormat(StrEnum):
    REL1000 = "rel1000"  # [x0, y0, x1, y1] in 0..1000 (what our prompts ask for; Qwen3-VL native)
    YXYX1000 = "yxyx1000"  # [y0, x0, y1, x1] in 0..1000 (Gemini native)
    PIXELS = "pixels"  # [x0, y0, x1, y1] in pixels of the image the model saw
    AUTO = "auto"  # rel1000 unless a coordinate exceeds 1000, then pixels


BOX_KEYS = ("bbox_2d", "box_2d", "bbox", "box")


def box_prompt(fmt: BoxFormat, width: int, height: int) -> tuple[str, str]:
    """(JSON key, description) asking a model for boxes in its native convention."""
    if fmt is BoxFormat.YXYX1000:
        return "box_2d", "[ymin, xmin, ymax, xmax], integers normalized to 0-1000"
    if fmt is BoxFormat.PIXELS:
        return "bbox", f"[x1, y1, x2, y2] in pixels of this {width}x{height} image"
    key = "bbox_2d" if fmt is BoxFormat.REL1000 else "bbox"
    return key, "[x1, y1, x2, y2], integers from 0 to 1000 relative to the image width (x) and height (y)"


def raw_box(entry: dict[str, object]) -> list[float] | None:
    for key in BOX_KEYS:
        value = entry.get(key)
        if isinstance(value, list):
            return value
    return None


def to_bbox(raw: Sequence[float], fmt: BoxFormat, width: int, height: int) -> BBox | None:
    """Converts one raw box; returns None for anything degenerate or malformed instead of failing the menu."""
    if len(raw) != 4:
        return None
    try:
        a, b, c, d = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    if fmt is BoxFormat.AUTO:
        fmt = BoxFormat.PIXELS if max(a, b, c, d) > 1000.5 else BoxFormat.REL1000
    if fmt is BoxFormat.YXYX1000:
        x0, y0, x1, y1 = b / 1000, a / 1000, d / 1000, c / 1000
    elif fmt is BoxFormat.PIXELS:
        x0, y0, x1, y1 = a / width, b / height, c / width, d / height
    else:
        x0, y0, x1, y1 = a / 1000, b / 1000, c / 1000, d / 1000
    x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
    y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
        return None
    return BBox(x0=x0, y0=y0, x1=x1, y1=y1)


def from_bbox(box: BBox, fmt: BoxFormat, width: int, height: int) -> list[int]:
    """The inverse of `to_bbox`: a page-relative box in the model's own convention, for prompts that show boxes."""
    if fmt is BoxFormat.YXYX1000:
        return [round(box.y0 * 1000), round(box.x0 * 1000), round(box.y1 * 1000), round(box.x1 * 1000)]
    if fmt is BoxFormat.PIXELS:
        return [round(box.x0 * width), round(box.y0 * height), round(box.x1 * width), round(box.y1 * height)]
    return [round(box.x0 * 1000), round(box.y0 * 1000), round(box.x1 * 1000), round(box.y1 * 1000)]


def to_tile(box: BBox, tile: BBox) -> BBox:
    """Maps a box relative to a tile back to the full page."""
    w, h = tile.x1 - tile.x0, tile.y1 - tile.y0
    return BBox(
        x0=tile.x0 + box.x0 * w,
        y0=tile.y0 + box.y0 * h,
        x1=min(1.0, tile.x0 + box.x1 * w),
        y1=min(1.0, tile.y0 + box.y1 * h),
    )
