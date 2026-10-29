import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from menubench.eval import evaluate_run
from menubench.runs import RunDir, RunInfo
from menubench.schema import (
    BBox,
    MenuAnnotation,
    MenuItem,
    MenuPrediction,
    Page,
    PriceAnnotation,
    PricePrediction,
    Source,
)
from menubench.server.app import Settings, create_app


def _setup(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    (data / "m1").mkdir(parents=True)
    Image.new("RGB", (100, 100), "white").save(data / "m1" / "page-0.png")
    box = BBox(x0=0.7, y0=0.1, x1=0.9, y1=0.15)
    ann = MenuAnnotation(
        menu_id="m1",
        source=Source.SYNTHETIC,
        lang="ru",
        template="t",
        pages=(Page(index=0, width=100, height=100, image="m1/page-0.png"),),
        items=(MenuItem(id="i1", page=0, name="Борщ", bbox=box),),
        prices=(PriceAnnotation(id="p1", page=0, value=Decimal(350), bbox=box, item_ids=("i1",)),),
    )
    (data / "m1" / "annotation.json").write_text(ann.model_dump_json(), encoding="utf-8")
    (data / "index.jsonl").write_text(json.dumps({"menu_id": "m1", "split": "dev"}) + "\n", encoding="utf-8")
    run = RunDir(tmp_path / "runs" / "r1")
    run.write_info(
        RunInfo(
            run_id="r1",
            config_name="c",
            config={"pipeline": "vlm_e2e", "models": {"vlm": "x"}},
            dataset=str(data),
            split="dev",
            started_at=datetime.now(UTC),
            menus=1,
        )
    )
    run.append_prediction(
        MenuPrediction(
            menu_id="m1",
            config="c",
            prices=(
                PricePrediction(page=0, value=Decimal(350), bbox=box, name="борщ", confidence=0.9),
                PricePrediction(page=0, value=Decimal(999), bbox=box, name="Щи", confidence=0.4),
            ),
        )
    )
    evaluate_run(run)
    return TestClient(create_app(Settings(runs_root=tmp_path / "runs", web_dist=tmp_path / "no-dist")))


def test_runs_api(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    runs = client.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == ["r1"]
    assert runs[0]["price_f1"] == round(2 * 0.5 * 1 / 1.5, 4)

    detail = client.get("/api/runs/r1").json()
    assert detail["menus"][0]["menu_id"] == "m1"
    assert "per_menu" not in detail["metrics"]

    review = client.get("/api/runs/r1/menus/m1").json()
    assert [o["outcome"] for o in review["outcomes"]] == ["correct", "spurious"]
    assert review["outcomes"][0]["gt_name"] == "Борщ"

    image = client.get("/api/runs/r1/menus/m1/pages/0")
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"


def test_not_found(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/r1/menus/..%2F..%2Fsecret/pages/0").status_code == 404
    assert client.get("/api/runs/r1/menus/m1/pages/5").status_code == 404
