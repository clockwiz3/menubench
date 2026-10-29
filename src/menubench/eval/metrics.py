"""Run-level metrics: extraction quality, selective prediction, cost and per-slice breakdowns."""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from menubench.eval.match import MenuMatch, Outcome, match_menu
from menubench.schema import MenuAnnotation, MenuPrediction

RISK_LEVELS = (0.01, 0.02, 0.05)


def _prf(tp: int, n_pred: int, n_gt: int) -> dict[str, float]:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gt if n_gt else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f, 4)}


@dataclass(frozen=True)
class Scored:
    confidence: float
    correct: bool


def risk_coverage(scored: list[Scored], gt_total: int) -> dict[str, Any]:
    """Sort by confidence; keeping the top-k predictions gives one point (coverage, risk) per k.

    AURC averages risk over every k. `safe_recall` is the business number: the share of all menu prices
    that can be placed automatically while the error rate among placed prices stays under the level.
    """
    if not scored:
        return {"aurc": None, "curve": [], "safe_recall": {str(r): 0.0 for r in RISK_LEVELS}}
    ordered = sorted(scored, key=lambda s: -s.confidence)
    n = len(ordered)
    errors = 0
    curve: list[tuple[float, float, float]] = []
    for k, s in enumerate(ordered, start=1):
        errors += not s.correct
        curve.append((k / n, errors / k, ordered[k - 1].confidence))
    aurc = sum(risk for _, risk, _ in curve) / n
    safe: dict[str, float] = {}
    for level in RISK_LEVELS:
        best = 0
        for k, (_, risk, _) in enumerate(curve, start=1):
            # Only cut where the confidence actually changes: a threshold cannot split tied scores.
            if risk <= level and (k == n or ordered[k].confidence < ordered[k - 1].confidence):
                best = max(best, k - round(risk * k))
        safe[str(level)] = round(best / gt_total, 4) if gt_total else 0.0
    step = max(1, n // 60)
    points = [
        {"coverage": round(c, 4), "risk": round(r, 4), "threshold": round(t, 4)}
        for i, (c, r, t) in enumerate(curve)
        if i % step == 0 or i == n - 1
    ]
    return {"aurc": round(aurc, 4), "curve": points, "safe_recall": safe}


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 3)
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1], 3)


def _summary(matches: list[MenuMatch], preds: list[MenuPrediction]) -> dict[str, Any]:
    tp = sum(m.tp for m in matches)
    pair_tp = sum(m.pair_tp for m in matches)
    n_pred = sum(len(m.matches) for m in matches)
    n_gt = sum(m.gt_current for m in matches)
    ious = [pm.iou for m in matches for pm in m.matches if pm.iou is not None and pm.gt_id]
    return {
        "menus": len(matches),
        "gt_prices": n_gt,
        "pred_prices": n_pred,
        "price": {"tp": tp, "fp": n_pred - tp, "fn": n_gt - tp, **_prf(tp, n_pred, n_gt)},
        "pair": {"tp": pair_tp, **_prf(pair_tp, n_pred, n_gt)},
        "name_accuracy": round(pair_tp / tp, 4) if tp else None,
        "crossed_as_current": sum(pm.outcome is Outcome.CROSSED for m in matches for pm in m.matches),
        "bbox_iou_mean": round(statistics.fmean(ious), 4) if ious else None,
        "cost_usd": round(sum(p.cost_usd for p in preds), 6),
    }


def evaluate(pairs: Iterable[tuple[MenuAnnotation, MenuPrediction]]) -> dict[str, Any]:
    pairs = list(pairs)
    matches = [match_menu(ann, pred) for ann, pred in pairs]

    scored = [
        Scored(pred.prices[pm.pred_index].confidence, pm.outcome is Outcome.CORRECT)
        for (_, pred), match in zip(pairs, matches, strict=True)
        for pm in match.matches
    ]
    gt_total = sum(m.gt_current for m in matches)
    latencies = [pred.latency_s for _, pred in pairs]
    costs = [pred.cost_usd for _, pred in pairs]

    result = _summary(matches, [p for _, p in pairs])
    result["selective"] = risk_coverage(scored, gt_total)
    result["cost"] = {
        "total_usd": round(sum(costs), 6),
        "per_menu_usd": round(statistics.fmean(costs), 6) if costs else 0.0,
    }
    result["latency_s"] = {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95)}

    slices: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for i, (ann, _) in enumerate(pairs):
        slices["template"][ann.template or "-"].append(i)
        slices["lang"][ann.lang].append(i)
        slices["source"][ann.source.value].append(i)
        slices["augment"][ann.augment.value if ann.augment else "clean"].append(i)
        for tag in ann.tags:
            slices["tag"][tag].append(i)
    result["slices"] = {
        dim: {
            key: {
                k: v
                for k, v in _summary([matches[i] for i in idx], [pairs[i][1] for i in idx]).items()
                if k in ("menus", "gt_prices", "price", "pair", "name_accuracy")
            }
            for key, idx in sorted(groups.items())
        }
        for dim, groups in slices.items()
    }
    result["per_menu"] = {
        m.menu_id: {
            "gt": m.gt_current,
            "pred": len(m.matches),
            "tp": m.tp,
            "pair_tp": m.pair_tp,
            "errors": len(m.matches) - m.pair_tp + len(m.missed),
            "cost_usd": pred.cost_usd,
            "latency_s": pred.latency_s,
        }
        for m, (_, pred) in zip(matches, pairs, strict=True)
    }
    return result
