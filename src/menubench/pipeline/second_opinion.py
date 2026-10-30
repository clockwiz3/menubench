"""A strong VLM reads the menu; the reference pipeline checks it independently.

The end-to-end model is accurate but does not know where it is wrong. The crop-attribution pipeline is weaker but
fails differently: it reads through OCR, looks at each price on its own crop and votes. Where the two agree on the
price and the item, a price can go on a screen; where they disagree, a person should look. Agreement and both
confidences are the signals the calibrator turns into a probability.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from menubench.calibration import Calibrator
from menubench.detect import find_candidates
from menubench.detect.refine import refine_prices
from menubench.eval.match import spatially_close
from menubench.eval.text import normalize
from menubench.link import LinkerConfig, arbitrate, decide
from menubench.llm.boxes import to_tile
from menubench.ocr import vlm_ocr
from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.pipeline.baselines import VlmEndToEnd
from menubench.pipeline.full import FullPipeline, Spend, _same
from menubench.schema import BBox, LinkDecision, MenuPrediction, PricePrediction


def _counterpart(price: PricePrediction, others: tuple[PricePrediction, ...]) -> PricePrediction | None:
    """The second opinion's price for the same spot: same value, same page, nearby if both have boxes."""
    same_value = [o for o in others if o.page == price.page and o.value == price.value]
    if price.bbox is not None:
        located = [o for o in same_value if o.bbox is None or spatially_close(o.bbox, price.bbox)]
        if located:
            return max(located, key=lambda o: o.bbox.iou(price.bbox) if o.bbox and price.bbox else 0.0)
        return None
    return same_value[0] if len(same_value) == 1 else None


_GENERIC = {"салат", "суп", "блюдо", "порция", "salad", "soup", "dish", "with", "and", "the"}


def _content_words(name: str | None) -> set[str]:
    return {w for w in normalize(name or "").split() if len(w) >= 4 and w not in _GENERIC}


def names_agree(reader: str | None, verifier: str | None) -> bool:
    """Same dish, read differently. The verifier reads one crop at a time, so on multi-line names it often returns
    one line, drops a word or swaps the order. Agreement means: near-identical text, or the verifier's distinctive
    words are all part of the reader's name. Generic words do not count, so a bare "Salad" agrees with nothing;
    the price itself already matched by value and position."""
    if _same(reader, verifier):
        return True
    ours, theirs = _content_words(reader), _content_words(verifier)
    return len(theirs) >= 1 and theirs <= ours


def anchor_to_ocr(prices: list[PricePrediction], ocr_prices: tuple[PricePrediction, ...]) -> list[PricePrediction]:
    """Moves each reader box onto the OCR-found occurrence of the same price nearest to it, one to one.

    The reader knows which item a price belongs to but places boxes loosely; OCR places them well but does not know
    the items. With repeated prices ("$10" twelve times) a loose box can sit closer to the wrong text than to its
    own price, so boxes are taken from OCR and only the pairing comes from the reader.
    """
    pairs = []
    for i, price in enumerate(prices):
        if price.bbox is None:
            continue
        height = price.bbox.y1 - price.bbox.y0
        cx, cy = (price.bbox.x0 + price.bbox.x1) / 2, (price.bbox.y0 + price.bbox.y1) / 2
        for j, other in enumerate(ocr_prices):
            if other.bbox is None or other.page != price.page or other.value != price.value:
                continue
            ox, oy = (other.bbox.x0 + other.bbox.x1) / 2, (other.bbox.y0 + other.bbox.y1) / 2
            distance = ((cx - ox) ** 2 + (cy - oy) ** 2) ** 0.5
            if distance <= max(4 * height, 0.06):
                pairs.append((distance, i, j))
    taken_prices: set[int] = set()
    taken_ocr: set[int] = set()
    moved = list(prices)
    for _, i, j in sorted(pairs):
        if i in taken_prices or j in taken_ocr:
            continue
        taken_prices.add(i)
        taken_ocr.add(j)
        moved[i] = prices[i].model_copy(update={"bbox": ocr_prices[j].bbox})
    return moved


def _inside(outer: BBox, inner: BBox) -> bool:
    ix = max(0.0, min(outer.x1, inner.x1) - max(outer.x0, inner.x0))
    iy = max(0.0, min(outer.y1, inner.y1) - max(outer.y0, inner.y0))
    return inner.area > 0 and ix * iy / inner.area >= 0.8


def box_on_prices(box: BBox, same_value: list[BBox], all_prices: list[BBox], max_ratio: float = 3.5) -> bool:
    """The reader's box sits on printed prices: it contains an OCR occurrence of its value and is not much larger
    than all OCR prices it contains together ("250/350 RSD" in one box is fine; a box over a whole line is not)."""
    if not any(_inside(box, b) for b in same_value):
        return False
    inner = [b for b in all_prices if _inside(box, b)]
    hull = BBox(
        x0=min(b.x0 for b in inner),
        y0=min(b.y0 for b in inner),
        x1=max(b.x1 for b in inner),
        y1=max(b.y1 for b in inner),
    )
    return box.area <= hull.area * max_ratio


def opinion_signals(price: PricePrediction, others: tuple[PricePrediction, ...]) -> dict[str, float]:
    other = _counterpart(price, others)
    duplicates = sum(1 for o in others if o.page == price.page and o.value == price.value)
    # Where OCR saw this price: a reader box far from every OCR occurrence of its value is placed loosely or on the
    # wrong text, even when the value and the item agree.
    same_value = [o for o in others if o.page == price.page and o.value == price.value and o.bbox is not None]
    box_iou = max((price.bbox.iou(o.bbox) for o in same_value if o.bbox), default=0.0) if price.bbox else 0.0
    # A reader box may cover two prices printed together ("250/350 RSD"); it is still on the price if it covers the
    # OCR occurrence almost fully and is not much larger. A box over a whole line stays off.
    box_on_price = (
        box_on_prices(
            price.bbox,
            [o.bbox for o in same_value if o.bbox],
            [o.bbox for o in others if o.bbox and o.page == price.page],
        )
        if price.bbox
        else False
    )
    return {
        "reader_conf": price.confidence,
        "verifier_found_price": float(other is not None),
        "verifier_agrees_on_item": float(other is not None and names_agree(price.name, other.name)),
        "verifier_conf": other.confidence if other is not None else 0.0,
        "verifier_agrees_and_confident": float(
            other is not None and names_agree(price.name, other.name) and other.confidence >= 0.8
        ),
        "value_ambiguous": float(duplicates > 1),
        "reader_has_box": float(price.bbox is not None),
        "box_iou_with_ocr": round(box_iou, 4),
        "box_on_ocr_price": float(box_iou >= 0.3 or box_on_price),
        "verifier_second_look": float(other is not None and other.signals.get("second_look", 0.0) > 0),
    }


class SecondOpinion(Pipeline):
    name = "second_opinion"
    roles = ("vlm", "ocr", "attribution")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        ids = {role: spec.id for role, spec in self.models.items()}
        # Boxes are fixed after both opinions are in (anchor to OCR, then snap to ink), not inside the reader.
        self.reader = VlmEndToEnd(self.client, {"vlm": ids["vlm"]}, {"refine_boxes": False})
        # The verifier runs uncalibrated: its own confidence is one of the signals, not the decision.
        verifier_params = {k: v for k, v in self.params.items() if k in ("passes", "tiebreak")}
        self.verifier = FullPipeline(
            self.client, {"ocr": ids["ocr"], "attribution": ids["attribution"]}, verifier_params
        )
        path = self.params.get("calibrator")
        self.calibrator = Calibrator.load(Path(path)) if path else None

    def estimate_calls(self, pages: int, prices_hint: int) -> list[tuple[str, int, float, int]]:
        return [("vlm", pages, 1.0, 2500), *self.verifier.estimate_calls(pages, prices_hint)]

    async def _link(
        self, menu: MenuInput, prices: list[PricePrediction], log: StageLog
    ) -> tuple[tuple[LinkDecision | None, ...], float]:
        """Strict linking; only prices both opinions trust may be linked without a person."""
        cfg = LinkerConfig(**self.params.get("linker", {}))
        decisions = [decide(p.name, menu.catalog, cfg, price_trusted=p.auto is not False) for p in prices]
        cost = 0.0
        arbiter = self.models.get("arbiter")
        if arbiter is not None:
            results = await asyncio.gather(
                *(
                    arbitrate(self.client, arbiter, p.name or "", str(p.value), d, menu.catalog)
                    for p, d in zip(prices, decisions, strict=True)
                )
            )
            decisions = [d for d, _ in results]
            cost = sum(c for _, c in results)
        await log.stage("link", mode="strict", decisions=[d.model_dump(mode="json") for d in decisions])
        return tuple(decisions), cost

    async def _second_look(
        self, menu: MenuInput, read: MenuPrediction, checked: MenuPrediction
    ) -> tuple[tuple[PricePrediction, ...], float]:
        """Where the reader has a price and the verifier saw nothing, the verifier reads that area again, at higher
        zoom and without being told what to expect. Whatever it finds there is attributed the usual way."""
        missing = [p for p in read.prices if p.bbox is not None and _counterpart(p, checked.prices) is None]
        if not missing:
            return checked.prices, 0.0
        spend = Spend()
        found: list[PricePrediction] = []
        lines = list(checked.lines)
        regions: list[tuple[int, BBox]] = []
        for price in missing:
            assert price.bbox is not None
            b, h = price.bbox, price.bbox.y1 - price.bbox.y0
            region = BBox(
                x0=max(0.0, b.x0 - 0.45), y0=max(0.0, b.y0 - 3 * h), x1=min(1.0, b.x1 + 0.05), y1=min(1.0, b.y1 + 3 * h)
            )
            for k, (page, other) in enumerate(regions):
                if page == price.page and region.iou(other) > 0:
                    region = BBox(
                        x0=min(region.x0, other.x0),
                        y0=min(region.y0, other.y0),
                        x1=max(region.x1, other.x1),
                        y1=max(region.y1, other.y1),
                    )
                    regions.pop(k)
                    break
            regions.append((price.page, region))
        for page, region in regions[:6]:
            image = menu.pages[page]
            w, hgt = image.size
            crop = image.crop(
                (round(region.x0 * w), round(region.y0 * hgt), round(region.x1 * w), round(region.y1 * hgt))
            )
            ocr = await vlm_ocr(self.client, self.verifier.models["ocr"], crop, page=page)
            spend.usd += ocr.cost_usd
            lines += [ln.model_copy(update={"bbox": to_tile(ln.bbox, region)}) for ln in ocr.lines]
        cands = find_candidates(lines)
        fresh = [
            c
            for c in cands
            if c.line >= len(checked.lines)
            and not any(
                o.value == c.parsed.value and o.bbox and spatially_close(o.bbox, c.bbox) for o in checked.prices
            )
        ]
        results = await asyncio.gather(
            *(self.verifier._attribute(menu.pages[lines[c.line].page], c, lines, cands, spend) for c in fresh)
        )
        for prediction, _ in results:
            if prediction is not None:
                found.append(prediction.model_copy(update={"signals": {**prediction.signals, "second_look": 1.0}}))
        return checked.prices + tuple(found), spend.usd

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        started = time.perf_counter()
        read, checked = await asyncio.gather(self.reader.process(menu, log), self.verifier.process(menu, log))
        second_look_cost = 0.0
        if self.params.get("second_look", True):
            before = len(checked.prices)
            verified, second_look_cost = await self._second_look(menu, read, checked)
            checked = checked.model_copy(update={"prices": verified})
            await log.stage("second_look", found=len(verified) - before, cost_usd=second_look_cost)
        prices = []
        target = float(self.params.get("target_risk", 0.01))
        for price in read.prices:
            signals = opinion_signals(price, checked.prices)
            auto = None
            confidence = round((signals["reader_conf"] + signals["verifier_agrees_on_item"]) / 2, 4)
            if self.calibrator is not None:
                confidence = round(self.calibrator.predict(signals), 4)
                threshold = self.calibrator.threshold(target)
                auto = threshold is not None and confidence >= threshold
            prices.append(price.model_copy(update={"confidence": confidence, "signals": signals, "auto": auto}))
        await log.stage(
            "second_opinion",
            agreed=sum(p.signals["verifier_agrees_on_item"] for p in prices),
            reader_only=sum(1 - p.signals["verifier_found_price"] for p in prices),
            verifier_prices=len(checked.prices),
        )
        if self.params.get("refine_boxes", False):
            prices = list(refine_prices(menu.pages, tuple(anchor_to_ocr(prices, checked.prices))))
        links: tuple[LinkDecision | None, ...] = ()
        link_cost = 0.0
        if self.params.get("link") and menu.catalog:
            links, link_cost = await self._link(menu, prices, log)
        return MenuPrediction(
            menu_id=menu.menu_id,
            config=self.name,
            prices=tuple(prices),
            links=links,
            lines=checked.lines,
            cost_usd=read.cost_usd + checked.cost_usd + second_look_cost + link_cost,
            latency_s=time.perf_counter() - started,
        )
