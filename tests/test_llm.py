import asyncio
import itertools
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image

from menubench.llm import CacheMiss, CacheMode, ImagePart, LLMClient, ResponseCache, parse_json, prompt
from menubench.llm.boxes import BoxFormat, to_bbox, to_tile
from menubench.ocr import plan_tiles, salvage
from menubench.schema import BBox


def _body(text: str, cost: float = 0.001) -> dict[str, Any]:
    return {"model": "m", "choices": [{"message": {"content": text}}], "usage": {"cost": cost}}


def _client(tmp_path: Path, handler: Any, mode: CacheMode = CacheMode.RECORD_MISSING) -> LLMClient:
    return LLMClient(
        api_key="test",
        cache=ResponseCache(tmp_path / "c.sqlite"),
        mode=mode,
        transport=httpx.MockTransport(handler),
    )


def test_box_formats() -> None:
    assert to_bbox([100, 200, 300, 400], BoxFormat.REL1000, 10, 10) == BBox(x0=0.1, y0=0.2, x1=0.3, y1=0.4)
    assert to_bbox([200, 100, 400, 300], BoxFormat.YXYX1000, 10, 10) == BBox(x0=0.1, y0=0.2, x1=0.3, y1=0.4)
    assert to_bbox([10, 20, 30, 40], BoxFormat.PIXELS, 100, 100) == BBox(x0=0.1, y0=0.2, x1=0.3, y1=0.4)
    assert to_bbox([10, 20, 1300, 40], BoxFormat.AUTO, 2000, 100) == BBox(x0=0.005, y0=0.2, x1=0.65, y1=0.4)
    assert to_bbox([5, 5, 5, 9], BoxFormat.REL1000, 1, 1) is None
    assert to_bbox(["a", 1, 2, 3], BoxFormat.REL1000, 1, 1) is None  # type: ignore[list-item]
    tile = BBox(x0=0, y0=0.5, x1=1, y1=1)
    assert to_tile(BBox(x0=0, y0=0, x1=1, y1=0.5), tile) == BBox(x0=0, y0=0.5, x1=1, y1=0.75)


def test_parse_json_variants() -> None:
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_salvage_recovers_lines_from_broken_json() -> None:
    broken = (
        '{"lines": [{"text": "Борщ", "box_2d": [1, 2, 3, 4], "box_2d": [5, 6, 7, 8]}, {"text": "350 ₽", "bbox": [9,'
    )
    assert salvage(broken) == [{"text": "Борщ", "bbox": [1.0, 2.0, 3.0, 4.0]}]


def test_tiles_cover_tall_pages_with_overlap() -> None:
    assert plan_tiles(1000, 1000) == [BBox(x0=0, y0=0, x1=1, y1=1)]
    tiles = plan_tiles(1000, 4000)
    assert len(tiles) == 3
    assert tiles[0].y0 == 0 and tiles[-1].y1 == 1
    assert all(a.y1 > b.y0 for a, b in itertools.pairwise(tiles))


def test_prompt_is_versioned() -> None:
    text, version = prompt("ocr")
    assert version.startswith("ocr.v") and "{{BOX_KEY}}" in text


def test_client_caches_and_replays(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=_body('{"ok": true}'))

    image = ImagePart.from_image(Image.new("RGB", (40, 20), "white"))

    async def scenario() -> None:
        client = _client(tmp_path, handler)
        first = await client.complete("m", "hi", images=[image], prompt_version="t.v1")
        second = await client.complete("m", "hi", images=[image], prompt_version="t.v1")
        assert not first.cached and second.cached
        assert client.meter.spent_usd == pytest.approx(0.001)
        await client.aclose()

        offline = _client(tmp_path, handler, CacheMode.REPLAY)
        assert (await offline.complete("m", "hi", images=[image], prompt_version="t.v1")).text == '{"ok": true}'
        with pytest.raises(CacheMiss):
            await offline.complete("m", "something else", prompt_version="t.v1")
        await offline.aclose()

    asyncio.run(scenario())
    assert len(calls) == 1
    assert calls[0]["messages"][0]["content"][1]["type"] == "image_url"


def test_client_retries_transient_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([httpx.Response(429, text="slow down"), httpx.Response(200, json=_body("done"))])
    monkeypatch.setattr(asyncio, "sleep", _instant)

    async def scenario() -> str:
        client = _client(tmp_path, lambda _: next(responses))
        result = await client.complete("m", "x")
        await client.aclose()
        return result.text

    assert asyncio.run(scenario()) == "done"


async def _instant(_: float) -> None:
    return None
