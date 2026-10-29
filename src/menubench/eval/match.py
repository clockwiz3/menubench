"""One-to-one matching of predicted prices to ground truth for a single menu."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from menubench.eval.text import similar
from menubench.schema import BBox, MenuAnnotation, MenuPrediction, PriceAnnotation, PriceKind, PricePrediction


class Outcome(StrEnum):
    CORRECT = "correct"  # right price, right item name
    WRONG_NAME = "wrong_name"  # right price, wrong or missing name
    CROSSED = "crossed"  # an old struck-through price reported as current
    SPURIOUS = "spurious"  # no such price on the menu (or not where the model says)


@dataclass(frozen=True)
class PriceMatch:
    pred_index: int
    gt_id: str | None
    outcome: Outcome
    iou: float | None


@dataclass(frozen=True)
class MenuMatch:
    menu_id: str
    matches: tuple[PriceMatch, ...]  # one per prediction, in prediction order
    missed: tuple[str, ...]  # current GT prices nobody predicted
    gt_current: int  # GT prices that should be extracted (crossed excluded)

    @property
    def tp(self) -> int:
        return sum(m.outcome in (Outcome.CORRECT, Outcome.WRONG_NAME) for m in self.matches)

    @property
    def pair_tp(self) -> int:
        return sum(m.outcome is Outcome.CORRECT for m in self.matches)


def spatially_close(pred: BBox, gt: BBox) -> bool:
    """VLM boxes are loose: accept a decent overlap or a center that lands near the true box."""
    if pred.iou(gt) >= 0.25:
        return True
    cx, cy = (pred.x0 + pred.x1) / 2, (pred.y0 + pred.y1) / 2
    margin = max(gt.y1 - gt.y0, 0.01)  # about one text line in every direction
    return gt.x0 - margin <= cx <= gt.x1 + margin and gt.y0 - margin <= cy <= gt.y1 + margin


def _same_value(pred: PricePrediction, gt: PriceAnnotation) -> bool:
    if pred.value != gt.value:
        return False
    if gt.kind is PriceKind.RANGE:
        return pred.value_max == gt.value_max
    return True


def _gt_names(gt: PriceAnnotation, names: dict[str, str]) -> list[str]:
    out = []
    for item_id in gt.item_ids:
        name = names[item_id]
        out.append(name)
        if gt.size_label:
            out.append(f"{name} {gt.size_label}")
    return out


def match_menu(annotation: MenuAnnotation, prediction: MenuPrediction) -> MenuMatch:
    names = {item.id: item.name for item in annotation.items}
    gts = list(annotation.prices)
    preds = list(prediction.prices)

    candidates: list[tuple[tuple[int, float, int], int, int]] = []
    for pi, pred in enumerate(preds):
        for gi, gt in enumerate(gts):
            if pred.page != gt.page or not _same_value(pred, gt):
                continue
            iou = pred.bbox.iou(gt.bbox) if pred.bbox else 0.0
            if pred.bbox is not None and not spatially_close(pred.bbox, gt.bbox):
                continue
            name_ok = similar(pred.name, _gt_names(gt, names))
            # Prefer located matches, then overlap, then a matching name to break ties among equal values.
            candidates.append(((int(pred.bbox is not None), iou, int(name_ok)), pi, gi))
    candidates.sort(key=lambda c: c[0], reverse=True)

    pred_to_gt: dict[int, int] = {}
    used_gt: set[int] = set()
    for _, pi, gi in candidates:
        if pi in pred_to_gt or gi in used_gt:
            continue
        pred_to_gt[pi] = gi
        used_gt.add(gi)

    matches = []
    for pi, pred in enumerate(preds):
        matched = pred_to_gt.get(pi)
        if matched is None:
            matches.append(PriceMatch(pi, None, Outcome.SPURIOUS, None))
            continue
        gt = gts[matched]
        overlap = pred.bbox.iou(gt.bbox) if pred.bbox else None
        if gt.kind is PriceKind.CROSSED:
            outcome = Outcome.CROSSED
        elif similar(pred.name, _gt_names(gt, names)):
            outcome = Outcome.CORRECT
        else:
            outcome = Outcome.WRONG_NAME
        matches.append(PriceMatch(pi, gt.id, outcome, overlap))

    current = [g for g in gts if g.kind is not PriceKind.CROSSED]
    missed = tuple(g.id for gi, g in enumerate(gts) if g.kind is not PriceKind.CROSSED and gi not in used_gt)
    return MenuMatch(prediction.menu_id, tuple(matches), missed, len(current))
