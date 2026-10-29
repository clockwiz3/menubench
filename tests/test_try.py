import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.schema import BBox, MenuPrediction, PricePrediction
from menubench.server import try_api
from menubench.server.app import Settings, create_app


class FakePipeline(Pipeline):
    name = "fake"
    roles = ()

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        await log.stage("ocr", lines=[{"text": "Борщ"}, {"text": "350 ₽"}], raw=["secret raw output"])
        await log.progress("price", done=1, total=1, item="Борщ")
        price = PricePrediction(
            page=0,
            value=Decimal(350),
            bbox=BBox(x0=0.6, y0=0.1, x1=0.7, y1=0.12),
            name="Борщ",
            confidence=0.99,
            auto=True,
        )
        return MenuPrediction(menu_id=menu.menu_id, config=self.name, prices=(price,), cost_usd=0.002)


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setattr(try_api, "build_pipeline", lambda cfg, client: FakePipeline(client, {}))
    settings = Settings(
        runs_root=tmp_path / "runs",
        web_dist=tmp_path / "x",
        data_root=tmp_path,
        try_uploads_per_ip=2,
        try_daily_budget_usd=0.003,
    )
    return TestClient(create_app(settings))


def test_job_streams_stage_summaries_and_returns_prices(client: TestClient) -> None:
    started = client.post("/api/try/jobs", files={"file": ("menu.jpg", _jpeg(), "image/jpeg")})
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    with client.stream("GET", f"/api/try/jobs/{job_id}/events") as stream:
        body = "".join(stream.iter_text())
    events = [
        json.loads(line[5:]) for line in body.splitlines() if line.startswith("data:") and line[5:].strip() != "{}"
    ]
    assert [e["stage"] for e in events] == ["ocr", "price", "done"]
    assert events[0]["lines"] == 2 and "secret" not in body  # counts only, never raw model output
    job = client.get(f"/api/try/jobs/{job_id}").json()
    assert job["status"] == "done" and job["prediction"]["prices"][0]["name"] == "Борщ"
    assert client.get(job["pages"][0]["url"]).status_code == 200


def test_limits_per_ip_and_budget(client: TestClient) -> None:
    for _ in range(2):
        r = client.post("/api/try/jobs", files={"file": ("menu.jpg", _jpeg(), "image/jpeg")})
        assert r.status_code == 202
        with client.stream("GET", f"/api/try/jobs/{r.json()['job_id']}/events") as s:
            "".join(s.iter_text())
    limits = client.get("/api/try/limits").json()
    assert not limits["enabled"]
    assert client.post("/api/try/jobs", files={"file": ("menu.jpg", _jpeg(), "image/jpeg")}).status_code == 429


def test_no_key_means_gallery_only(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert client.get("/api/try/limits").json()["enabled"] is False
    assert client.post("/api/try/jobs", files={"file": ("menu.jpg", _jpeg(), "image/jpeg")}).status_code == 503
    assert isinstance(client.get("/api/try/gallery").json(), list)


def test_sections_switch_off_the_annotator(tmp_path: Path) -> None:
    app = create_app(Settings(runs_root=tmp_path, web_dist=tmp_path / "x", data_root=tmp_path, sections=("try",)))
    client = TestClient(app)
    assert client.get("/api/annotate/menus").status_code == 404
    assert client.get("/api/try/limits").status_code == 200
