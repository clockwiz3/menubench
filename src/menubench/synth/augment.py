"""Photo-like degradations with exact box bookkeeping.

Every geometric step is a homography; boxes are moved by mapping their four corners and taking the axis-aligned
hull, so ground truth stays exact (up to that hull) after rotation and perspective.
"""

from __future__ import annotations

import io
import math
import random
from collections.abc import Callable

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from menubench.schema import AugmentLevel, BBox, MenuAnnotation

Point = tuple[float, float]
Mapper = Callable[[float, float], Point]  # normalized coords of the original page -> normalized coords of output


def _homography(src: list[Point], dst: list[Point]) -> np.ndarray:
    rows = []
    for (x, y), (u, v) in zip(src, dst, strict=True):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, -u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.asarray(rows, dtype=float))
    h: np.ndarray = vt[-1].reshape(3, 3)
    return np.asarray(h / h[2, 2], dtype=float)


def _apply(h: np.ndarray, x: float, y: float) -> Point:
    u, v, w = h @ np.array([x, y, 1.0])
    return float(u / w), float(v / w)


def _warp(
    img: Image.Image, dst: list[Point], out_size: tuple[int, int], fill: tuple[int, int, int]
) -> tuple[Image.Image, np.ndarray]:
    """Warps the full image onto quad `dst` (pixels) of a new canvas. Returns (image, src->dst homography)."""
    w, h = img.size
    src = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    forward = _homography(src, dst)
    inverse = np.linalg.inv(forward)
    inverse = inverse / inverse[2, 2]
    coeffs = tuple(float(c) for c in inverse.flatten()[:8])
    warped = img.transform(out_size, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC, fillcolor=fill)
    return warped, forward


def _geometric(img: Image.Image, rng: random.Random, level: AugmentLevel) -> tuple[Image.Image, Mapper]:
    w, h = img.size
    if level is AugmentLevel.SCAN:
        angle = math.radians(rng.uniform(-1.8, 1.8))
        jitter = 0.0
        margin = 0.03
        background = (rng.randint(225, 245),) * 3
    else:
        angle = math.radians(rng.uniform(-4.5, 4.5))
        jitter = rng.uniform(0.02, 0.07)
        margin = 0.08
        background = (rng.randint(40, 120), rng.randint(35, 100), rng.randint(30, 90))  # a table under the menu

    cx, cy = w / 2, h / 2
    corners = [(0.0, 0.0), (float(w), 0.0), (float(w), float(h)), (0.0, float(h))]
    moved = []
    for x, y in corners:
        dx, dy = x - cx, y - cy
        rx = cx + dx * math.cos(angle) - dy * math.sin(angle)
        ry = cy + dx * math.sin(angle) + dy * math.cos(angle)
        moved.append((rx + rng.uniform(-jitter, jitter) * w, ry + rng.uniform(-jitter, jitter) * h))
    xs, ys = [p[0] for p in moved], [p[1] for p in moved]
    pad_x, pad_y = margin * w, margin * h
    shift = (-min(xs) + pad_x, -min(ys) + pad_y)
    dst = [(x + shift[0], y + shift[1]) for x, y in moved]
    out_w = round(max(xs) - min(xs) + 2 * pad_x)
    out_h = round(max(ys) - min(ys) + 2 * pad_y)

    warped, forward = _warp(img, dst, (out_w, out_h), background)

    def mapper(x: float, y: float) -> Point:
        u, v = _apply(forward, x * w, y * h)
        return u / out_w, v / out_h

    return warped, mapper


def _photometric(img: Image.Image, rng: random.Random, level: AugmentLevel) -> Image.Image:
    arr = np.asarray(img.convert("RGB"), dtype=np.float64)
    hgt, wid = arr.shape[:2]
    if level is AugmentLevel.SCAN:
        tint = np.array([rng.uniform(0.95, 1.0), rng.uniform(0.94, 0.99), rng.uniform(0.88, 0.96)])
        arr = arr * tint
        arr += np.random.default_rng(rng.randrange(2**32)).normal(0, rng.uniform(3, 7), arr.shape)
    else:
        # Uneven light: a linear gradient across the page plus a soft glare spot.
        gx, gy = np.meshgrid(np.linspace(-1, 1, wid), np.linspace(-1, 1, hgt))
        a, b = rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25)
        light = 1.0 + a * gx + b * gy
        if rng.random() < 0.6:
            sx, sy = rng.uniform(-0.7, 0.7), rng.uniform(-0.7, 0.7)
            radius = rng.uniform(0.15, 0.35)
            light += rng.uniform(0.25, 0.6) * np.exp(-((gx - sx) ** 2 + (gy - sy) ** 2) / (2 * radius**2))
        arr = arr * light[..., None] * rng.uniform(0.85, 1.0)
        warm = np.array([rng.uniform(1.0, 1.06), 1.0, rng.uniform(0.9, 1.0)])
        arr = arr * warm
        arr += np.random.default_rng(rng.randrange(2**32)).normal(0, rng.uniform(4, 10), arr.shape)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    blur = rng.uniform(0.3, 0.7) if level is AugmentLevel.SCAN else rng.uniform(0.5, 1.3)
    out = out.filter(ImageFilter.GaussianBlur(blur))
    if level is AugmentLevel.PHOTO:
        factor = rng.uniform(0.6, 0.85)
        out = out.resize((round(out.width * factor), round(out.height * factor)), Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=rng.randint(70, 85) if level is AugmentLevel.SCAN else rng.randint(55, 75))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def _move(box: BBox, mapper: Mapper) -> BBox:
    pts = [mapper(x, y) for x, y in ((box.x0, box.y0), (box.x1, box.y0), (box.x1, box.y1), (box.x0, box.y1))]
    x0 = min(max(min(p[0] for p in pts), 0.0), 1.0)
    y0 = min(max(min(p[1] for p in pts), 0.0), 1.0)
    x1 = min(max(max(p[0] for p in pts), 0.0), 1.0)
    y1 = min(max(max(p[1] for p in pts), 0.0), 1.0)
    return BBox(x0=x0, y0=y0, x1=max(x1, x0 + 1e-6), y1=max(y1, y0 + 1e-6))


def augment(
    png: bytes, annotation: MenuAnnotation, level: AugmentLevel, rng: random.Random
) -> tuple[bytes, str, MenuAnnotation]:
    """Returns (image bytes, file extension, annotation with moved boxes). CLEAN returns the input untouched."""
    if level is AugmentLevel.CLEAN:
        return png, "png", annotation.model_copy(update={"augment": AugmentLevel.CLEAN})
    img = Image.open(io.BytesIO(png)).convert("RGB")
    warped, mapper = _geometric(img, rng, level)
    final = _photometric(warped, rng, level)
    buf = io.BytesIO()
    final.save(buf, format="JPEG", quality=92)
    page = annotation.pages[0]
    new_page = page.model_copy(
        update={"width": final.width, "height": final.height, "image": page.image.replace(".png", ".jpg")}
    )
    moved = annotation.model_copy(
        update={
            "pages": (new_page,),
            "items": tuple(i.model_copy(update={"bbox": _move(i.bbox, mapper)}) for i in annotation.items),
            "prices": tuple(p.model_copy(update={"bbox": _move(p.bbox, mapper)}) for p in annotation.prices),
            "lines": tuple(ln.model_copy(update={"bbox": _move(ln.bbox, mapper)}) for ln in annotation.lines),
            "augment": level,
        }
    )
    return buf.getvalue(), "jpg", moved


def debug_overlay(img: Image.Image, annotation: MenuAnnotation) -> Image.Image:
    """Draws price boxes; used by tests and when eyeballing a new augmentation."""
    out = img.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    for p in annotation.prices:
        b = p.bbox
        draw.rectangle(
            (b.x0 * out.width, b.y0 * out.height, b.x1 * out.width, b.y1 * out.height), outline="red", width=2
        )
    return out
