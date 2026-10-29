import asyncio
import json
from decimal import Decimal
from typing import Any

from PIL import Image

from menubench.llm import ImagePart, LLMClient, LLMResponse
from menubench.pipeline.base import MenuInput, StageLog
from menubench.pipeline.full import FullPipeline, Vote, _vote, heuristic_confidence
from menubench.schema import PriceKind


class ScriptedClient(LLMClient):
    """Answers by prompt type: OCR gets fixed lines, attribution gets a scripted sequence of names."""

    def __init__(self, names: list[str | None]) -> None:
        super().__init__(api_key="test")
        self.names = names
        self.calls = 0

    async def complete(self, model: str, prompt: str, **kwargs: Any) -> LLMResponse:
        if "OCR engine" in prompt:
            lines = [
                {"text": "Борщ", "bbox_2d": [50, 100, 300, 130]},
                {"text": "350 ₽", "bbox_2d": [800, 100, 900, 130]},
                {"text": "Тел. 8 800 555-35-35", "bbox_2d": [300, 900, 700, 930]},
            ]
            return LLMResponse(json.dumps({"lines": lines}), model, 0.001, 0.1, False)
        name = self.names[min(self.calls, len(self.names) - 1)]
        self.calls += 1
        body = {"status": "current_price", "item": name, "size": None, "confidence": 0.9}
        return LLMResponse(json.dumps(body, ensure_ascii=False), model, 0.0001, 0.1, False)


def _run(names: list[str | None]) -> tuple[Any, ScriptedClient]:
    client = ScriptedClient(names)
    pipeline = FullPipeline(client, {"ocr": "qwen/x", "attribution": "qwen/y"})
    menu = MenuInput("m", [Image.new("RGB", (1000, 1000), "white")])
    log = StageLog()
    prediction = asyncio.run(pipeline.process(menu, log))
    return (prediction, log), client


def test_agreeing_passes_give_one_confident_price() -> None:
    (prediction, log), client = _run(["Борщ", "Борщ"])
    assert client.calls == 2
    [price] = prediction.prices
    assert price.value == Decimal(350) and price.name == "Борщ" and price.kind is PriceKind.SINGLE
    assert price.signals["agreement"] == 1.0
    assert price.confidence > 0.7
    assert [s["stage"] for s in log.trace["stages"]] == ["ocr", "detect", "attribution"]


def test_disagreement_triggers_a_third_pass_and_lowers_confidence() -> None:
    (prediction, _), client = _run(["Борщ", "Щи", "Борщ"])
    assert client.calls == 3
    [price] = prediction.prices
    assert price.name == "Борщ"
    assert price.signals["agreement"] < 1.0


def test_echoed_price_falls_back_to_geometry() -> None:
    (prediction, _), _ = _run(["350 ₽", "350 ₽"])
    [price] = prediction.prices
    assert price.name == "Борщ"
    assert price.signals["geometry_fallback"] == 1.0
    assert price.confidence < 0.5


def test_vote_groups_fuzzy_spellings() -> None:
    votes = [
        Vote("current_price", "Солянка", None, 0.9, ""),
        Vote("current_price", "солянка", None, 0.8, ""),
        Vote("current_price", "Борщ", None, 0.99, ""),
    ]
    winner, agreement = _vote(votes)
    assert winner.item in {"Солянка", "солянка"} and agreement == 2 / 3


def test_heuristic_confidence_is_monotone() -> None:
    base = {
        "agreement": 0.5,
        "model_conf": 0.5,
        "geometry_agrees": 0.0,
        "name_in_ocr": 0.0,
        "column_support": 0.0,
        "has_currency": 0.0,
        "votes": 2.0,
    }
    for key in ("agreement", "model_conf", "geometry_agrees", "name_in_ocr", "column_support", "has_currency"):
        assert heuristic_confidence({**base, key: 1.0}) > heuristic_confidence(base)


def test_image_part_downscales() -> None:
    part = ImagePart.from_image(Image.new("RGB", (4000, 1000)), max_side=1000)
    assert (part.width, part.height) == (1000, 250)
