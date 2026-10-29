"""OCR stage alone: used to compare OCR models before anything is built on top of them."""

from __future__ import annotations

import time

from menubench.ocr import vlm_ocr
from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.schema import MenuPrediction


class OcrOnly(Pipeline):
    name = "ocr_only"
    roles = ("ocr",)

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        started = time.perf_counter()
        lines, cost = [], 0.0
        for page_no, image in enumerate(menu.pages):
            result = await vlm_ocr(self.client, self.models["ocr"], image, page=page_no)
            lines += result.lines
            cost += result.cost_usd
            await log.stage(
                "ocr",
                page=page_no,
                lines=[line.model_dump(mode="json") for line in result.lines],
                tiles=[t.model_dump(mode="json") for t in result.tiles],
                raw=result.raw,
                errors=result.errors,
                cost_usd=result.cost_usd,
            )
        return MenuPrediction(
            menu_id=menu.menu_id,
            config=self.name,
            lines=tuple(lines),
            cost_usd=cost,
            latency_s=time.perf_counter() - started,
        )
