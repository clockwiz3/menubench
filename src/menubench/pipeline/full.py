"""The reference pipeline: OCR → price detection → VLM attribution with voting → confidence → decision.

Each detected price is shown to a VLM on a crop with the price outlined in red, together with the nearby OCR
lines. Two independent passes look at different crops; if they disagree a third pass breaks the tie. Agreement,
the model's own confidence, geometry and OCR evidence are kept as `signals`; M8 calibrates them into one number.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw

from menubench.detect import Candidate, find_candidates, median_height
from menubench.eval.text import cer, normalize
from menubench.llm import ImagePart, LLMError, parse_json, prompt
from menubench.ocr import vlm_ocr
from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.pipeline.baselines import attribute_by_geometry
from menubench.prices import parse_price
from menubench.schema import BBox, MenuPrediction, PriceKind, PricePrediction, TextLine


@dataclass(frozen=True)
class View:
    """One way to look at a price: crop extent around it (in line heights / page widths) and sampling."""

    left: float  # page widths to the left of the price
    up: float  # line heights above
    down: float  # line heights below
    temperature: float


VIEWS = (
    View(left=0.55, up=4, down=1.5, temperature=0.0),
    View(left=1.0, up=5, down=2.5, temperature=0.3),
    View(left=0.75, up=7, down=3, temperature=0.6),
)


@dataclass
class Spend:
    """Per-menu cost; the pipeline object is shared by menus processed concurrently."""

    usd: float = 0.0


@dataclass
class Vote:
    status: str
    item: str | None
    size: str | None
    confidence: float
    raw: str


def _crop(image: Image.Image, price: BBox, view: View, line_h: float) -> tuple[Image.Image, BBox]:
    w, h = image.size
    region = BBox(
        x0=max(0.0, price.x0 - view.left),
        y0=max(0.0, price.y0 - view.up * line_h),
        x1=min(1.0, price.x1 + 0.03),
        y1=min(1.0, price.y1 + view.down * line_h),
    )
    crop = image.crop((round(region.x0 * w), round(region.y0 * h), round(region.x1 * w), round(region.y1 * h)))
    crop = crop.convert("RGB")
    draw = ImageDraw.Draw(crop)
    pad = 4
    draw.rectangle(
        (
            (price.x0 - region.x0) * w - pad,
            (price.y0 - region.y0) * h - pad,
            (price.x1 - region.x0) * w + pad,
            (price.y1 - region.y0) * h + pad,
        ),
        outline=(230, 30, 30),
        width=3,
    )
    if crop.width < 640:  # small crops get upscaled so the model sees legible text
        factor = 640 / crop.width
        crop = crop.resize((640, round(crop.height * factor)), Image.Resampling.LANCZOS)
    return crop, region


def _nearby(lines: list[TextLine], region: BBox, exclude: int, limit: int = 14) -> list[str]:
    cx, cy = (region.x0 + region.x1) / 2, (region.y0 + region.y1) / 2
    inside = [
        (abs((ln.bbox.y0 + ln.bbox.y1) / 2 - cy) + abs((ln.bbox.x0 + ln.bbox.x1) / 2 - cx) * 0.3, ln.text)
        for i, ln in enumerate(lines)
        if i != exclude
        and ln.bbox.x1 > region.x0
        and ln.bbox.x0 < region.x1
        and ln.bbox.y1 > region.y0
        and ln.bbox.y0 < region.y1
    ]
    return [text for _, text in sorted(inside)[:limit]]


def _same(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return a == b
    return normalize(a) == normalize(b) or cer(a, b) <= 0.15


def _vote(votes: list[Vote]) -> tuple[Vote, float]:
    """Majority over item names (fuzzy-equal names count together). Returns (winner, agreement share)."""
    groups: list[list[Vote]] = []
    for v in votes:
        for g in groups:
            if _same(g[0].item, v.item) and g[0].status == v.status:
                g.append(v)
                break
        else:
            groups.append([v])
    best = max(groups, key=lambda g: (len(g), statistics.fmean(x.confidence for x in g)))
    # Prefer the spelling that occurs most often inside the winning group.
    spelling = Counter(v.item for v in best if v.item).most_common(1)
    winner = Vote(
        status=best[0].status,
        item=spelling[0][0] if spelling else None,
        size=next((v.size for v in best if v.size), None),
        confidence=statistics.fmean(v.confidence for v in best),
        raw="",
    )
    return winner, len(best) / len(votes)


def _column_support(cand: Candidate, cands: list[Candidate]) -> float:
    """Prices on menus line up: right edges in a column or rows with several sizes."""
    aligned = sum(1 for c in cands if c is not cand and abs(c.bbox.x1 - cand.bbox.x1) < 0.015)
    return min(1.0, aligned / 4)


class FullPipeline(Pipeline):
    name = "full"
    roles = ("ocr", "attribution")

    def estimate_calls(self, pages: int, prices_hint: int) -> list[tuple[str, int, float, int]]:
        passes = int(self.params.get("passes", 2))
        return [("ocr", pages, 1.0, 2500), ("attribution", int(prices_hint * (passes + 0.3)), 0.15, 60)]

    async def _ask(
        self, image: Image.Image, cand: Candidate, lines: list[TextLine], view_no: int, spend: Spend
    ) -> Vote:
        spec = self.models["attribution"]
        view = VIEWS[view_no]
        crop, region = _crop(image, cand.bbox, view, median_height(lines))
        text, version = prompt("attribution")
        nearby = _nearby(lines, region, cand.line)
        filled = text.replace("{{PRICE}}", cand.text).replace(
            "{{LINES}}", "\n".join(f"- {t}" for t in nearby) or "- (none)"
        )
        response = await self.client.complete(
            spec.id,
            filled,
            images=[ImagePart.from_image(crop, max_side=spec.max_image_side)],
            prompt_version=version,
            fallback_models=spec.fallback,
            temperature=view.temperature,
            max_tokens=300,
            variant=view_no,
        )
        spend.usd += response.cost_usd
        try:
            data: Any = parse_json(response.text)
        except ValueError:
            return Vote("unknown", None, None, 0.0, response.text)
        if not isinstance(data, dict):
            return Vote("unknown", None, None, 0.0, response.text)
        try:
            confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        item = data.get("item")
        size = data.get("size")
        if item and (parse_price(str(item)) is not None or normalize(str(item)) == normalize(cand.text)):
            item, confidence = None, 0.0  # the model echoed the price back instead of naming the item
        return Vote(
            status=str(data.get("status") or "current_price"),
            item=str(item).strip() if item else None,
            size=str(size).strip() if size else None,
            confidence=confidence,
            raw=response.text,
        )

    async def _attribute(
        self, image: Image.Image, cand: Candidate, lines: list[TextLine], cands: list[Candidate], spend: Spend
    ) -> tuple[PricePrediction | None, dict[str, Any]]:
        passes = int(self.params.get("passes", 2))
        votes = list(await asyncio.gather(*(self._ask(image, cand, lines, v, spend) for v in range(passes))))
        if passes >= 2 and not all(_same(votes[0].item, v.item) for v in votes[1:]) and passes < len(VIEWS):
            votes.append(await self._ask(image, cand, lines, passes, spend))
        winner, agreement = _vote(votes)

        geo_name, _, geo_rule = attribute_by_geometry(cand, lines)
        fallback = winner.item is None and geo_name is not None
        if fallback:  # no usable vote: geometry names it, and confidence says so
            winner.item, agreement = geo_name, 0.0
        signals = {
            "agreement": agreement,
            "votes": float(len(votes)),
            "model_conf": winner.confidence,
            "geometry_agrees": float(_same(geo_name, winner.item)),
            "geometry_rule_row": float(geo_rule == "row_left"),
            "merged_line": float(cand.merged_name is not None),
            "column_support": _column_support(cand, cands),
            "has_currency": float(cand.parsed.currency is not None),
            "name_in_ocr": float(any(_same(winner.item, ln.text) for ln in lines)),
            "geometry_fallback": float(fallback),
        }
        trace = {
            "price": cand.text,
            "votes": [{"status": v.status, "item": v.item, "size": v.size, "confidence": v.confidence} for v in votes],
            "winner": winner.item,
            "status": winner.status,
            "geometry": geo_name,
            "signals": signals,
        }
        if winner.status in ("not_price", "old_price"):
            return None, trace
        kind = cand.parsed.kind
        if winner.size and kind is PriceKind.SINGLE:
            kind = PriceKind.SIZE_VARIANT
        confidence = heuristic_confidence(signals)
        prediction = PricePrediction(
            page=lines[cand.line].page,
            value=cand.parsed.value,
            value_max=cand.parsed.value_max,
            currency=cand.parsed.currency,
            kind=kind,
            bbox=cand.bbox,
            name=winner.item,
            confidence=confidence,
            signals=signals,
        )
        return prediction, trace

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        started = time.perf_counter()
        spend = Spend()
        prices: list[PricePrediction] = []
        all_lines: list[TextLine] = []
        for page_no, image in enumerate(menu.pages):
            ocr = await vlm_ocr(self.client, self.models["ocr"], image, page=page_no)
            spend.usd += ocr.cost_usd
            lines = ocr.lines
            all_lines += lines
            await log.stage("ocr", page=page_no, lines=[x.model_dump(mode="json") for x in lines], errors=ocr.errors)
            cands = find_candidates(lines)
            await log.stage(
                "detect",
                page=page_no,
                candidates=[{"text": c.text, "bbox": c.bbox.model_dump(), "merged": c.merged_name} for c in cands],
            )
            results = await asyncio.gather(
                *(self._attribute(image, c, lines, cands, spend) for c in cands), return_exceptions=True
            )
            decisions = []
            for cand, result in zip(cands, results, strict=True):
                if isinstance(result, LLMError):
                    raise result  # budget or provider exhausted: fail the menu loudly
                if isinstance(result, BaseException):
                    decisions.append({"price": cand.text, "error": repr(result)})
                    continue
                prediction, trace = result
                decisions.append(trace)
                if prediction is not None:
                    prices.append(prediction)
            await log.stage("attribution", page=page_no, decisions=decisions)
        return MenuPrediction(
            menu_id=menu.menu_id,
            config=self.name,
            prices=tuple(prices),
            lines=tuple(all_lines),
            cost_usd=spend.usd,
            latency_s=time.perf_counter() - started,
        )


def heuristic_confidence(s: dict[str, float]) -> float:
    """Hand-set combination used until a calibrator is fitted (M8). Kept monotone in every signal."""
    score = 0.35 * s["agreement"] + 0.25 * s["model_conf"] + 0.15 * s["geometry_agrees"]
    score += 0.1 * s["name_in_ocr"] + 0.1 * s["column_support"] + 0.05 * s["has_currency"]
    if s["votes"] > 2 and s["agreement"] < 0.67:
        score *= 0.6  # three passes and still no majority
    return round(min(1.0, max(0.0, score)), 4)
