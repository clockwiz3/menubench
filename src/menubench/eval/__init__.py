"""Scoring predictions against ground truth."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from menubench.data import Dataset
from menubench.eval.metrics import evaluate
from menubench.runs import RunDir


def evaluate_run(run: RunDir) -> dict[str, Any]:
    """Score every menu the run attempted. A failed menu carries `error` and no prices: all of it is missed."""
    info = run.info()
    dataset = Dataset(Path(info.dataset))
    pairs = [(dataset.annotation(p.menu_id), p) for p in run.predictions()]
    metrics = evaluate(pairs)
    metrics["run_id"] = info.run_id
    metrics["config_name"] = info.config_name
    metrics["failed_menus"] = sum(p.error is not None for _, p in pairs)
    run.write_metrics(metrics)
    return metrics


__all__ = ["evaluate", "evaluate_run"]
