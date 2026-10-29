"""Turns pipeline signals into a calibrated probability that a price is right, and fixes the auto-place threshold.

Fitted on the dev split only: logistic regression over the signals, then isotonic regression on its output so
that "0.9" means "right about 90% of the time". The operating threshold for a target error rate is chosen on dev
and then frozen; the test split only measures how well that frozen threshold holds.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from menubench.data import Dataset
from menubench.eval.match import Outcome, match_menu
from menubench.eval.metrics import expected_calibration_error
from menubench.runs import RunDir
from menubench.schema import PricePrediction

__all__ = ["Calibrator", "choose_thresholds", "expected_calibration_error", "fit", "labelled"]


class Calibrator(BaseModel):
    features: list[str]
    coef: list[float]
    intercept: float
    iso_x: list[float]
    iso_y: list[float]
    thresholds: dict[str, float]  # target risk ("0.01") -> minimal calibrated confidence to auto-place
    fitted_on: str
    samples: int
    positives: int

    def predict(self, signals: dict[str, float]) -> float:
        z = self.intercept + sum(c * float(signals.get(f, 0.0)) for f, c in zip(self.features, self.coef, strict=True))
        raw = 1 / (1 + math.exp(-z))
        return float(np.interp(raw, self.iso_x, self.iso_y)) if self.iso_x else raw

    def threshold(self, risk: float) -> float | None:
        return self.thresholds.get(str(risk))

    @classmethod
    def load(cls, path: Path) -> Calibrator:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=1), encoding="utf-8")


def labelled(run: RunDir) -> list[tuple[PricePrediction, bool]]:
    """Every predicted price of a run with its label: right price and right item."""
    dataset = Dataset(Path(run.info().dataset))
    out = []
    for prediction in run.predictions():
        match = match_menu(dataset.annotation(prediction.menu_id), prediction)
        for pm in match.matches:
            out.append((prediction.prices[pm.pred_index], pm.outcome is Outcome.CORRECT))
    return out


def choose_thresholds(probs: Iterable[float], labels: Iterable[bool], risks: tuple[float, ...]) -> dict[str, float]:
    """Lowest threshold whose kept set stays within each target risk on the fitting data."""
    pairs = sorted(zip(probs, labels, strict=True), key=lambda p: -p[0])
    out: dict[str, float] = {}
    for risk in risks:
        errors, best = 0, None
        for k, (p, ok) in enumerate(pairs, start=1):
            errors += not ok
            next_differs = k == len(pairs) or pairs[k][0] < p
            if next_differs and errors / k <= risk:
                best = p
        out[str(risk)] = 1.01 if best is None else round(best, 6)  # 1.01: nothing qualifies, never auto-place
    return out


def fit(
    samples: list[tuple[PricePrediction, bool]],
    fitted_on: str,
    risks: tuple[float, ...] = (0.01, 0.02, 0.05),
    only: list[str] | None = None,
) -> Calibrator:
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    features = sorted({k for p, _ in samples for k in p.signals if only is None or k in only})
    if not features:
        raise ValueError("predictions carry no signals; calibrate a pipeline that records them")
    x = np.array([[p.signals.get(f, 0.0) for f in features] for p, _ in samples], dtype=float)
    y = np.array([ok for _, ok in samples], dtype=int)
    if len(set(y)) < 2:
        raise ValueError("need both right and wrong predictions to calibrate")
    logit = LogisticRegression(C=1.0, max_iter=1000).fit(x, y)
    raw = logit.predict_proba(x)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw, y)
    grid = np.linspace(0, 1, 101)
    calibrator = Calibrator(
        features=features,
        coef=[float(c) for c in logit.coef_[0]],
        intercept=float(logit.intercept_[0]),
        iso_x=[float(v) for v in grid],
        iso_y=[float(v) for v in iso.predict(grid)],
        thresholds={},
        fitted_on=fitted_on,
        samples=len(samples),
        positives=int(y.sum()),
    )
    probs = [calibrator.predict(p.signals) for p, _ in samples]
    calibrator.thresholds = choose_thresholds(probs, [ok for _, ok in samples], risks)
    return calibrator
