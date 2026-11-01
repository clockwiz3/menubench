"""Straightens tilted menu photos before models read them, and maps their boxes back to the original photo.

On a tilted photo a printed row slopes, so a model reading it pairs names and prices across rows and places boxes
half a line off. The skew is estimated from the page itself: text rows give the sharpest horizontal ink profile
when they are level. Only rotation is undone; perspective stays. Boxes found on the straightened page come back as
the axis-aligned hull of the rotated box, which is how the synthetic ground truth treats rotation too.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

from menubench.schema import BBox

MAX_ANGLE = 12.0  # degrees; beyond this a page is more likely sideways or a collage than tilted
MIN_ANGLE = 0.6  # below this rotation costs more (resampling, a new model call) than it gives
MIN_GAIN = 1.15  # the best angle's profile must beat the unrotated one by this much to count
WORK_SIDE = 900  # the estimate runs on a downscaled copy


@dataclass(frozen=True)
class Straightened:
    """How a page was rotated: `angle` degrees counter-clockwise, from `src` size to `dst` size (pixels)."""

    angle: float
    src: tuple[int, int]
    dst: tuple[int, int]

    def _map(self, points: list[tuple[float, float]], forward: bool) -> list[tuple[float, float]]:
        (sw, sh), (dw, dh) = self.src, self.dst
        a = math.radians(self.angle if forward else -self.angle)
        cos, sin = math.cos(a), math.sin(a)
        (fw, fh), (tw, th) = ((sw, sh), (dw, dh)) if forward else ((dw, dh), (sw, sh))
        out = []
        for x, y in points:
            dx, dy = x - fw / 2, y - fh / 2
            # A counter-clockwise turn on screen, where y points down.
            out.append((tw / 2 + dx * cos + dy * sin, th / 2 - dx * sin + dy * cos))
        return out

    def _box(self, box: BBox, forward: bool) -> BBox:
        (fw, fh), (tw, th) = (self.src, self.dst) if forward else (self.dst, self.src)
        corners = [
            (box.x0 * fw, box.y0 * fh),
            (box.x1 * fw, box.y0 * fh),
            (box.x1 * fw, box.y1 * fh),
            (box.x0 * fw, box.y1 * fh),
        ]
        pts = self._map(corners, forward)
        xs = [min(max(x / tw, 0.0), 1.0) for x, _ in pts]
        ys = [min(max(y / th, 0.0), 1.0) for _, y in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        return BBox(x0=x0, y0=y0, x1=max(x1, x0 + 1e-4), y1=max(y1, y0 + 1e-4))

    def to_original(self, box: BBox) -> BBox:
        """A box on the straightened page, as the hull of the same region on the original photo."""
        return self._box(box, forward=False)

    def to_straight(self, box: BBox) -> BBox:
        return self._box(box, forward=True)


def _ink(img: Image.Image) -> np.ndarray:
    """Strokes darker or lighter than their surroundings, as a 0/1 map; flat areas and gradients drop out."""
    gray = img.convert("L")
    scale = WORK_SIDE / max(gray.size)
    if scale < 1:
        gray = gray.resize(
            (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))), Image.Resampling.BILINEAR
        )
    local = np.asarray(gray.filter(ImageFilter.BoxBlur(12)), dtype=np.float32)
    diff = np.abs(np.asarray(gray, dtype=np.float32) - local)
    return (diff > max(float(np.percentile(diff, 90)), 12.0)).astype(np.uint8) * 255


def _sharpness(ink: Image.Image, angle: float) -> float:
    rows = np.asarray(ink.rotate(angle, resample=Image.Resampling.NEAREST, expand=False), dtype=np.float32).sum(axis=1)
    return float(np.square(np.diff(rows)).sum())


def estimate_skew(img: Image.Image) -> tuple[float, float]:
    """(angle, gain): the counter-clockwise turn in degrees that levels the text rows, and how much sharper the row
    profile gets with it compared with leaving the page as is."""
    ink = Image.fromarray(_ink(img))
    base = _sharpness(ink, 0.0) or 1.0
    coarse = max(np.arange(-MAX_ANGLE, MAX_ANGLE + 1e-6, 0.5), key=lambda a: _sharpness(ink, float(a)))
    fine = max(np.arange(coarse - 0.5, coarse + 0.5 + 1e-6, 0.1), key=lambda a: _sharpness(ink, float(a)))
    angle = round(float(fine), 1)
    return angle, _sharpness(ink, angle) / base


def straighten(img: Image.Image) -> tuple[Image.Image, Straightened | None]:
    """The page turned level, or the page itself (and None) when it is already level or the estimate is unsure."""
    angle, gain = estimate_skew(img)
    if abs(angle) < MIN_ANGLE or gain < MIN_GAIN:
        return img, None
    rgb = img.convert("RGB")
    arr = np.asarray(rgb)
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    fill = tuple(int(v) for v in np.median(border, axis=0))
    turned = rgb.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=fill)
    return turned, Straightened(angle=angle, src=rgb.size, dst=turned.size)
