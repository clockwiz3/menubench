import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from menubench.eval import evaluate, evaluate_run
from menubench.eval.match import Outcome, match_menu
from menubench.eval.metrics import Scored, risk_coverage
from menubench.eval.text import cer, normalize
from menubench.runs import RunDir, RunInfo
from menubench.schema import (
    BBox,
    MenuAnnotation,
    MenuItem,
    MenuPrediction,
    Page,
    PriceAnnotation,
    PriceKind,
    PricePrediction,
    Source,
)


def _box(y: float, x0: float = 0.8) -> BBox:
    return BBox(x0=x0, y0=y, x1=x0 + 0.1, y1=y + 0.03)


def _menu() -> MenuAnnotation:
    items = (
        MenuItem(id="i1", page=0, name="Борщ", bbox=_box(0.1, 0.1)),
        MenuItem(id="i2", page=0, name="Солянка сборная", bbox=_box(0.2, 0.1)),
        MenuItem(id="i3", page=0, name="Латте", bbox=_box(0.3, 0.1)),
    )
    prices = (
        PriceAnnotation(id="p1", page=0, value=Decimal(350), bbox=_box(0.1), item_ids=("i1",)),
        PriceAnnotation(id="p2", page=0, value=Decimal(420), bbox=_box(0.2), item_ids=("i2",)),
        PriceAnnotation(
            id="p2old",
            page=0,
            value=Decimal(500),
            kind=PriceKind.CROSSED,
            bbox=_box(0.2, 0.65),
            item_ids=("i2",),
        ),
        PriceAnnotation(
            id="p3",
            page=0,
            value=Decimal(250),
            kind=PriceKind.SIZE_VARIANT,
            size_label="S",
            bbox=_box(0.3),
            item_ids=("i3",),
        ),
    )
    return MenuAnnotation(
        menu_id="m1",
        source=Source.SYNTHETIC,
        lang="ru",
        template="t",
        pages=(Page(index=0, width=1000, height=1000, image="m1/page-0.png"),),
        items=items,
        prices=prices,
    )


def _pred(value: int, y: float | None, name: str | None, conf: float = 0.9, x0: float = 0.8) -> PricePrediction:
    return PricePrediction(
        page=0, value=Decimal(value), bbox=_box(y, x0) if y is not None else None, name=name, confidence=conf
    )


def test_normalize_and_cer() -> None:
    assert normalize("  Солянка «Сборная»! ") == "солянка сборная"
    assert normalize("Ёжик") == "ежик"
    assert cer("Борщь", "Борщ") == pytest.approx(0.25)
    assert cer("", "") == 0.0


def test_oracle_scores_perfectly() -> None:
    menu = _menu()
    pred = MenuPrediction(
        menu_id="m1",
        config="oracle",
        prices=(
            _pred(350, 0.1, "борщ"),
            _pred(420, 0.2, "Солянка сборная"),
            _pred(250, 0.3, "Латте S"),
        ),
    )
    m = evaluate([(menu, pred)])
    assert m["price"]["f1"] == 1.0
    assert m["pair"]["f1"] == 1.0
    assert m["gt_prices"] == 3  # the crossed-out price is not something to extract


def test_outcomes() -> None:
    menu = _menu()
    pred = MenuPrediction(
        menu_id="m1",
        config="x",
        prices=(
            _pred(350, 0.1, "Щи"),  # right price, wrong item
            _pred(500, 0.2, "Солянка", x0=0.65),  # old crossed price reported as current
            _pred(999, 0.5, "Компот"),  # not on the menu
            _pred(420, 0.8, "Солянка сборная"),  # right value, wrong place
        ),
    )
    match = match_menu(menu, pred)
    assert [m.outcome for m in match.matches] == [
        Outcome.WRONG_NAME,
        Outcome.CROSSED,
        Outcome.SPURIOUS,
        Outcome.SPURIOUS,
    ]
    assert set(match.missed) == {"p2", "p3"}


def test_value_only_match_when_no_box() -> None:
    match = match_menu(_menu(), MenuPrediction(menu_id="m1", config="x", prices=(_pred(420, None, "солянка сборная"),)))
    assert match.matches[0].outcome is Outcome.CORRECT


def test_risk_coverage() -> None:
    scored = [Scored(0.9, True), Scored(0.8, True), Scored(0.7, False), Scored(0.6, True)]
    rc = risk_coverage(scored, gt_total=5)
    assert rc["aurc"] == pytest.approx((0 + 0 + 1 / 3 + 1 / 4) / 4, abs=1e-4)
    assert rc["safe_recall"]["0.01"] == pytest.approx(2 / 5)


def test_tied_confidence_cannot_be_split() -> None:
    rc = risk_coverage([Scored(0.5, True), Scored(0.5, False)], gt_total=2)
    assert rc["safe_recall"]["0.01"] == 0.0


def test_evaluate_run(tmp_path: Path) -> None:
    data = tmp_path / "data"
    (data / "m1").mkdir(parents=True)
    (data / "m1" / "annotation.json").write_text(_menu().model_dump_json(), encoding="utf-8")
    (data / "index.jsonl").write_text(json.dumps({"menu_id": "m1", "split": "test"}) + "\n", encoding="utf-8")
    run = RunDir(tmp_path / "runs" / "r1")
    run.write_info(RunInfo(run_id="r1", config_name="c", dataset=str(data), split="test", started_at=datetime.now(UTC)))
    run.append_prediction(MenuPrediction(menu_id="m1", config="c", error="timeout"))
    metrics = evaluate_run(run)
    assert metrics["failed_menus"] == 1
    assert metrics["price"]["recall"] == 0.0
    assert run.metrics() == metrics
