"""VLM-as-OCR: lines of text with page-relative boxes."""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from menubench.eval.text import normalize
from menubench.llm import ImagePart, LLMClient, parse_json, prompt
from menubench.llm.boxes import box_prompt, raw_box, to_bbox, to_tile
from menubench.llm.models import ModelSpec
from menubench.schema import BBox, TextLine


@dataclass
class OcrResult:
    lines: list[TextLine]
    cost_usd: float = 0.0
    latency_s: float = 0.0  # wall time; tiles run in parallel
    raw: list[str] = field(default_factory=list)
    tiles: list[BBox] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def plan_tiles(width: int, height: int, max_aspect: float = 1.5, overlap: float = 0.08) -> list[BBox]:
    """Tall pages are cut into horizontal bands so text stays legible after the model's downscale."""
    aspect = height / width
    if aspect <= max_aspect:
        return [BBox(x0=0, y0=0, x1=1, y1=1)]
    n = math.ceil(aspect / max_aspect)
    band = 1 / n
    pad = band * overlap
    return [BBox(x0=0, y0=max(0.0, i * band - pad), x1=1, y1=min(1.0, (i + 1) * band + pad)) for i in range(n)]


def _crop(image: Image.Image, tile: BBox) -> Image.Image:
    w, h = image.size
    return image.crop((round(tile.x0 * w), round(tile.y0 * h), round(tile.x1 * w), round(tile.y1 * h)))


_SALVAGE = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"(?:bbox_2d|box_2d|bbox|box)"\s*:\s*\[([^\]]*)\]')


def ocr_schema(key: str) -> dict[str, Any]:
    box = {"type": "array", "items": {"type": "integer"}}
    line = {
        "type": "object",
        "properties": {"text": {"type": "string"}, key: box},
        "required": ["text", key],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"lines": {"type": "array", "items": line}},
        "required": ["lines"],
        "additionalProperties": False,
    }


def salvage(text: str) -> list[dict[str, Any]]:
    """Recovers {text, box} pairs from malformed JSON (duplicate keys, missing commas, cut-off output)."""
    entries = []
    for m in _SALVAGE.finditer(text):
        try:
            value = json.loads(f'"{m.group(1)}"')
            box = [float(v) for v in m.group(2).split(",")]
        except ValueError:
            continue
        entries.append({"text": value, "bbox": box})
    return entries


def _parse_lines(text: str, spec: ModelSpec, part: ImagePart, tile: BBox, page: int) -> tuple[list[TextLine], bool]:
    salvaged = False
    try:
        data: Any = parse_json(text)
    except (ValueError, TypeError):
        data, salvaged = salvage(text), True
        if not data:
            raise
    entries = data.get("lines", []) if isinstance(data, dict) else data
    lines = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not str(entry.get("text", "")).strip():
            continue
        box = to_bbox(raw_box(entry) or [], spec.box_format, part.width, part.height)
        if box is None:
            continue
        lines.append(TextLine(page=page, text=str(entry["text"]).strip(), bbox=to_tile(box, tile)))
    return lines, salvaged


def _dedupe(lines: list[TextLine]) -> list[TextLine]:
    """Overlapping tiles see the same line twice; keep the first copy."""
    kept: list[TextLine] = []
    for line in lines:
        key = normalize(line.text)
        if any(normalize(k.text) == key and k.bbox.iou(line.bbox) > 0.3 for k in kept):
            continue
        kept.append(line)
    return sorted(kept, key=lambda line: (round(line.bbox.y0, 3), line.bbox.x0))


async def vlm_ocr(client: LLMClient, spec: ModelSpec, image: Image.Image, page: int = 0) -> OcrResult:
    text, version = prompt("ocr")
    tiles = plan_tiles(*image.size)

    async def one(tile: BBox) -> tuple[list[TextLine], str, float, float, str | None]:
        part = ImagePart.from_image(_crop(image, tile), max_side=spec.max_image_side)
        key, box_spec = box_prompt(spec.box_format, part.width, part.height)
        response = await client.complete(
            spec.id,
            text.replace("{{BOX_KEY}}", key).replace("{{BOX_SPEC}}", box_spec),
            images=[part],
            prompt_version=version,
            fallback_models=spec.fallback,
            max_tokens=8000,
            json_schema=ocr_schema(key) if spec.structured_output else None,
        )
        try:
            lines, salvaged = _parse_lines(response.text, spec, part, tile, page)
            error = f"malformed JSON, salvaged {len(lines)} lines" if salvaged else None
        except (ValueError, TypeError) as exc:
            lines, error = [], f"unparseable OCR output: {exc}"
        return lines, response.text, response.cost_usd, response.latency_s, error

    results = await asyncio.gather(*(one(t) for t in tiles))
    all_lines = [line for lines, *_ in results for line in lines]
    return OcrResult(
        lines=_dedupe(all_lines),
        cost_usd=sum(r[2] for r in results),
        latency_s=max(r[3] for r in results),
        raw=[r[1] for r in results],
        tiles=tiles,
        errors=[r[4] for r in results if r[4]],
    )
