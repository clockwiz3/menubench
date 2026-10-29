import random
from decimal import Decimal

import pytest

from menubench.calibration import choose_thresholds, fit
from menubench.eval.linking import evaluate_linking
from menubench.eval.match import match_menu
from menubench.eval.metrics import expected_calibration_error
from menubench.link import LinkerConfig, canon, decide, similarity
from menubench.schema import (
    BBox,
    CatalogEntry,
    LinkCandidate,
    LinkDecision,
    MenuAnnotation,
    MenuItem,
    MenuPrediction,
    Page,
    PriceAnnotation,
    PricePrediction,
    Source,
)

CATALOG = (
    CatalogEntry(id="c1", name="ГОР-012 Солянка сбор. 300г"),
    CatalogEntry(id="c2", name="Солянка рыбная"),
    CatalogEntry(id="c3", name="BORSCH UKR"),
    CatalogEntry(id="c4", name="Морс клюкв."),
)


def test_canon_strips_till_noise() -> None:
    assert canon("ГОР-012 Солянка сбор. 300г") == canon("Солянка сбор.")
    assert canon("Щи") == "schi"


def test_similarity_handles_abbreviations_and_translit() -> None:
    assert similarity("Солянка сборная", "ГОР-012 Солянка сбор. 300г") > 0.9
    assert similarity("Морс клюквенный", "Морс клюкв.") > 0.9
    assert similarity("Солянка сборная", "Морс клюкв.") < 0.4


def test_decisions() -> None:
    cfg = LinkerConfig()
    assert decide("Морс клюквенный", CATALOG, cfg).action == "link"
    # The match is clear, but the price on the menu is not trusted: no automatic link.
    assert decide("Морс клюквенный", CATALOG, cfg, price_trusted=False).action == "hint"
    hint = decide("Солянка", CATALOG, cfg)
    assert hint.action == "hint" and {c.catalog_id for c in hint.candidates} >= {"c1", "c2"}
    assert decide("Тирамису", CATALOG, cfg).action == "abstain"
    assert decide(None, CATALOG, cfg).action == "abstain"


def _menu() -> MenuAnnotation:
    box = BBox(x0=0.8, y0=0.1, x1=0.9, y1=0.13)
    box2 = BBox(x0=0.8, y0=0.2, x1=0.9, y1=0.23)
    return MenuAnnotation(
        menu_id="m",
        source=Source.SYNTHETIC,
        lang="ru",
        pages=(Page(index=0, width=10, height=10, image="m/p.png"),),
        items=(
            MenuItem(id="i1", page=0, name="Морс клюквенный", bbox=box, catalog_id="c4"),
            MenuItem(id="i2", page=0, name="Тирамису", bbox=box2, catalog_id=None),
        ),
        prices=(
            PriceAnnotation(id="p1", page=0, value=Decimal(150), bbox=box, item_ids=("i1",)),
            PriceAnnotation(id="p2", page=0, value=Decimal(390), bbox=box2, item_ids=("i2",)),
        ),
        catalog=CATALOG,
    )


def test_linking_metrics_punish_wrong_links_only() -> None:
    ann = _menu()
    box = ann.prices[0].bbox
    box2 = ann.prices[1].bbox
    pred = MenuPrediction(
        menu_id="m",
        config="x",
        prices=(
            PricePrediction(page=0, value=Decimal(150), bbox=box, name="Морс клюквенный", confidence=0.9),
            PricePrediction(page=0, value=Decimal(390), bbox=box2, name="Тирамису", confidence=0.9),
        ),
        links=(
            LinkDecision(action="link", catalog_id="c3"),  # wrong item on a screen
            LinkDecision(action="hint", candidates=(LinkCandidate(catalog_id="c1", score=0.5),), reason="?"),
        ),
    )
    m = evaluate_linking([(ann, pred, match_menu(ann, pred))])
    assert m is not None
    assert m["wrong_link_rate"] == 1.0
    assert m["decisions"] == {"link_wrong": 1, "hint_no_target": 1}


def test_thresholds_respect_target_risk() -> None:
    probs = [0.99, 0.98, 0.97, 0.9, 0.8, 0.7]
    labels = [True, True, True, False, True, False]
    t = choose_thresholds(probs, labels, (0.01, 0.3))
    assert t["0.01"] == 0.97  # top three are all right
    assert t["0.3"] == 0.8  # 1 error in 5 kept
    assert choose_thresholds([0.5], [False], (0.01,))["0.01"] > 1  # nothing qualifies: never auto-place


def test_fit_improves_calibration_on_separable_signals() -> None:
    rng = random.Random(0)
    samples = []
    for _ in range(400):
        good = rng.random() < 0.8
        agreement = 1.0 if good or rng.random() < 0.2 else 0.5
        signals = {"agreement": agreement, "noise": rng.random()}
        samples.append((PricePrediction(page=0, value=Decimal(1), confidence=0.5, signals=signals), good))
    cal = fit(samples, fitted_on="test")
    labels = [ok for _, ok in samples]
    after = expected_calibration_error([cal.predict(p.signals) for p, _ in samples], labels)["ece"]
    before = expected_calibration_error([0.5] * len(samples), labels)["ece"]
    assert isinstance(after, float) and isinstance(before, float) and after < before
    assert cal.coef[cal.features.index("agreement")] > 0


def test_fit_refuses_one_class() -> None:
    sample = PricePrediction(page=0, value=Decimal(1), confidence=0.5, signals={"a": 1.0})
    with pytest.raises(ValueError):
        fit([(sample, True)] * 5, fitted_on="x")
