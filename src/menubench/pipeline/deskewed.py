"""Runs any pipeline on straightened pages and returns its boxes on the original photos (`params.deskew: true`)."""

from __future__ import annotations

from typing import Any

from menubench.detect.deskew import Straightened, straighten
from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.schema import MenuPrediction


class Deskewed(Pipeline):
    name = "deskewed"
    roles = ()

    def __init__(self, inner: Pipeline) -> None:
        self.inner = inner
        self.client = inner.client
        self.models = inner.models
        self.params = inner.params

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        turned = [straighten(page) for page in menu.pages]
        await log.stage("deskew", angles=[t.angle if t else 0.0 for _, t in turned])
        prediction = await self.inner.process(MenuInput(menu.menu_id, [img for img, _ in turned]), log)
        return to_original(prediction, [t for _, t in turned])

    def estimate_calls(self, pages: int, prices_hint: int) -> list[tuple[str, int, float, int]]:
        return self.inner.estimate_calls(pages, prices_hint)


def to_original(prediction: MenuPrediction, turns: list[Straightened | None]) -> MenuPrediction:
    """Maps every price and OCR line box from the straightened pages back onto the photos as they were."""

    def back(page: int, box: Any) -> Any:
        turn = turns[page] if page < len(turns) else None
        return turn.to_original(box) if turn and box is not None else box

    return prediction.model_copy(
        update={
            "prices": tuple(p.model_copy(update={"bbox": back(p.page, p.bbox)}) for p in prediction.prices),
            "lines": tuple(ln.model_copy(update={"bbox": back(ln.page, ln.bbox)}) for ln in prediction.lines),
        }
    )
