"""Baselines every other configuration is compared against.

- VlmEndToEnd: one image, one call, the model lists prices and items itself. Confidence is self-reported.
- OcrHeuristic: OCR lines, then pure geometry: the name is the nearest text to the left on the same row,
  or the nearest same-size line above (cards). No LLM after OCR.
"""

from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any

from menubench.detect import Candidate, find_candidates, h_overlap, is_size_label, median_height, v_overlap
from menubench.llm import ImagePart, parse_json, prompt
from menubench.llm.boxes import box_prompt, raw_box, to_bbox
from menubench.ocr import vlm_ocr
from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.prices import parse_price
from menubench.schema import MenuPrediction, PriceKind, PricePrediction, TextLine


def e2e_schema(key: str) -> dict[str, Any]:
    entry = {
        "type": "object",
        "properties": {
            "price_text": {"type": "string"},
            "item": {"type": "string"},
            "size": {"type": ["string", "null"]},
            key: {"type": "array", "items": {"type": "integer"}},
            "confidence": {"type": "number"},
        },
        "required": ["price_text", "item", "size", key, "confidence"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"prices": {"type": "array", "items": entry}},
        "required": ["prices"],
        "additionalProperties": False,
    }


def _confidence(raw: Any, default: float = 0.5) -> float:
    try:
        return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return default


class VlmEndToEnd(Pipeline):
    name = "vlm_e2e"
    roles = ("vlm",)

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        started = time.perf_counter()
        spec = self.models["vlm"]
        text, version = prompt("e2e")
        prices: list[PricePrediction] = []
        cost = 0.0
        for page_no, image in enumerate(menu.pages):
            part = ImagePart.from_image(image, max_side=spec.max_image_side)
            key, box_spec = box_prompt(spec.box_format, part.width, part.height)
            response = await self.client.complete(
                spec.id,
                text.replace("{{BOX_KEY}}", key).replace("{{BOX_SPEC}}", box_spec),
                images=[part],
                prompt_version=version,
                fallback_models=spec.fallback,
                max_tokens=8000,
                json_schema=e2e_schema(key) if spec.structured_output else None,
            )
            cost += response.cost_usd
            data = parse_json(response.text)
            entries = data.get("prices", []) if isinstance(data, dict) else data
            page_prices = []
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                parsed = parse_price(str(entry.get("price_text", "")))
                if parsed is None:
                    try:  # the model sometimes drops the currency or adds words; keep the number
                        digits = str(entry.get("price_text", "")).replace(" ", "").replace(",", ".")
                        value = Decimal("".join(ch for ch in digits if ch.isdigit() or ch == "."))
                    except InvalidOperation:
                        continue
                    kind, value_max, currency = PriceKind.SINGLE, None, None
                else:
                    value, value_max, kind, currency = parsed.value, parsed.value_max, parsed.kind, parsed.currency
                if entry.get("size"):
                    kind = PriceKind.SIZE_VARIANT
                box = to_bbox(raw_box(entry) or [], spec.box_format, part.width, part.height)
                page_prices.append(
                    PricePrediction(
                        page=page_no,
                        value=value,
                        value_max=value_max,
                        currency=currency,
                        kind=kind,
                        bbox=box,
                        name=str(entry.get("item") or "") or None,
                        confidence=_confidence(entry.get("confidence")),
                    )
                )
            prices += page_prices
            await log.stage(
                "e2e",
                page=page_no,
                raw=response.text,
                prices=[p.model_dump(mode="json") for p in page_prices],
                cost_usd=response.cost_usd,
            )
        return MenuPrediction(
            menu_id=menu.menu_id,
            config=self.name,
            prices=tuple(prices),
            cost_usd=cost,
            latency_s=time.perf_counter() - started,
        )


def attribute_by_geometry(cand: Candidate, lines: list[TextLine]) -> tuple[str | None, float, str]:
    """Returns (name, confidence, rule). The rules are deliberately simple; they are a baseline."""
    if cand.merged_name:
        return cand.merged_name, 0.85, "same_line"
    price_box = cand.bbox
    typical = median_height(lines)

    def usable(i: int, line: TextLine) -> bool:
        return (
            i != cand.line
            and line.page == lines[cand.line].page
            and parse_price(line.text) is None
            and not is_size_label(line.text)
        )

    row = [
        (price_box.x0 - line.bbox.x1, line)
        for i, line in enumerate(lines)
        if usable(i, line) and v_overlap(line.bbox, price_box) >= 0.5 and line.bbox.x1 <= price_box.x0 + 0.01
    ]
    if row:
        return min(row, key=lambda r: r[0])[1].text, 0.8, "row_left"

    height = price_box.y1 - price_box.y0
    above = [
        (price_box.y0 - line.bbox.y1, line)
        for i, line in enumerate(lines)
        if usable(i, line)
        and line.bbox.y1 <= price_box.y0 + height * 0.3
        and price_box.y0 - line.bbox.y1 <= 4 * typical
        and (h_overlap(line.bbox, price_box) > 0 or abs(line.bbox.x0 - price_box.x0) < 0.05)
        and (line.bbox.y1 - line.bbox.y0) >= 0.9 * typical  # skip small-print descriptions
    ]
    if above:
        return min(above, key=lambda a: a[0])[1].text, 0.5, "above"
    return None, 0.1, "none"


class OcrHeuristic(Pipeline):
    name = "ocr_heuristic"
    roles = ("ocr",)

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        started = time.perf_counter()
        prices: list[PricePrediction] = []
        all_lines: list[TextLine] = []
        cost = 0.0
        for page_no, image in enumerate(menu.pages):
            ocr = await vlm_ocr(self.client, self.models["ocr"], image, page=page_no)
            cost += ocr.cost_usd
            lines = ocr.lines
            all_lines += lines
            await log.stage("ocr", page=page_no, lines=[x.model_dump(mode="json") for x in lines], raw=ocr.raw)
            candidates = find_candidates(lines)
            decisions = []
            for cand in candidates:
                name, conf, rule = attribute_by_geometry(cand, lines)
                prices.append(
                    PricePrediction(
                        page=page_no,
                        value=cand.parsed.value,
                        value_max=cand.parsed.value_max,
                        currency=cand.parsed.currency,
                        kind=cand.parsed.kind,
                        bbox=cand.bbox,
                        name=name,
                        confidence=conf,
                    )
                )
                decisions.append({"price": cand.text, "name": name, "rule": rule})
            await log.stage("attribution", page=page_no, decisions=decisions)
        return MenuPrediction(
            menu_id=menu.menu_id,
            config=self.name,
            prices=tuple(prices),
            lines=tuple(all_lines),
            cost_usd=cost,
            latency_s=time.perf_counter() - started,
        )
