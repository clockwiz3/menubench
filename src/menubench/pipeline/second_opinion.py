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
from menubench.detect.refine import refine_prices
from menubench.eval.match import spatially_close
from menubench.eval.text import normalize
from menubench.link import LinkerConfig, arbitrate, decide
from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.pipeline.baselines import VlmEndToEnd
from menubench.pipeline.full import FullPipeline, _same
from menubench.schema import LinkDecision, MenuPrediction, PricePrediction


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


def opinion_signals(price: PricePrediction, others: tuple[PricePrediction, ...]) -> dict[str, float]:
    other = _counterpart(price, others)
    duplicates = sum(1 for o in others if o.page == price.page and o.value == price.value)
    # Where OCR saw this price: a reader box far from every OCR occurrence of its value is placed loosely or on the
    # wrong text, even when the value and the item agree.
    same_value = [o for o in others if o.page == price.page and o.value == price.value and o.bbox is not None]
    box_iou = max((price.bbox.iou(o.bbox) for o in same_value if o.bbox), default=0.0) if price.bbox else 0.0
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
        "box_on_ocr_price": float(box_iou >= 0.3),
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

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        started = time.perf_counter()
        read, checked = await asyncio.gather(self.reader.process(menu, log), self.verifier.process(menu, log))
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
            cost_usd=read.cost_usd + checked.cost_usd + link_cost,
            latency_s=time.perf_counter() - started,
        )
