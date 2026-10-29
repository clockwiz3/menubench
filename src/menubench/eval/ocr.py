"""OCR quality against the exact line-level ground truth of synthetic menus."""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from typing import Any

from rapidfuzz import fuzz

from menubench.eval.text import cer, normalize
from menubench.schema import BBox, MenuAnnotation, MenuPrediction, TextLine, TextRole


def _coverage(gt: BBox, pred: BBox) -> float:
    """Share of the ground-truth box covered by the predicted one."""
    ix = max(0.0, min(gt.x1, pred.x1) - max(gt.x0, pred.x0))
    iy = max(0.0, min(gt.y1, pred.y1) - max(gt.y0, pred.y0))
    return ix * iy / gt.area if gt.area else 0.0


def find_line(gt: TextLine, preds: list[TextLine]) -> tuple[TextLine | None, float]:
    """Best predicted line that sits on the GT line and contains its text. Returns (line, CER)."""
    target = normalize(gt.text)
    best: tuple[TextLine | None, float] = (None, 1.0)
    for pred in preds:
        if pred.page != gt.page or _coverage(gt.bbox, pred.bbox) < 0.4:
            continue
        text = normalize(pred.text)
        # A model may merge "name ... price" into one line; containment counts, exact match is better.
        error = min(cer(pred.text, gt.text), 1 - fuzz.partial_ratio(target, text) / 100 if text else 1.0)
        if error < best[1]:
            best = (pred, error)
    return best


def text_found(gt: TextLine, preds: list[TextLine], max_cer: float) -> bool:
    """Recognition without localization: the text appears somewhere on the same page."""
    target = normalize(gt.text)
    return any(
        p.page == gt.page
        and (cer(p.text, gt.text) <= max_cer or fuzz.partial_ratio(target, normalize(p.text)) >= 100 * (1 - max_cer))
        for p in preds
    )


def evaluate_ocr(pairs: Iterable[tuple[MenuAnnotation, MenuPrediction]], max_cer: float = 0.2) -> dict[str, Any] | None:
    found = total = price_found = price_total = text_ok = price_text_ok = 0
    errors: list[float] = []
    ious: list[float] = []
    pred_lines = 0
    any_lines = False
    for ann, pred in pairs:
        if not pred.lines:
            continue
        any_lines = True
        preds = list(pred.lines)
        pred_lines += len(preds)
        for gt in ann.lines:
            line, error = find_line(gt, preds)
            ok = line is not None and error <= max_cer
            anywhere = ok or text_found(gt, preds, max_cer)
            total += 1
            found += ok
            text_ok += anywhere
            if gt.role is TextRole.PRICE:
                price_total += 1
                price_found += ok
                price_text_ok += anywhere
            if line is not None:
                errors.append(error)
                ious.append(gt.bbox.iou(line.bbox))
    if not any_lines:
        return None
    return {
        "gt_lines": total,
        "pred_lines": pred_lines,
        "text_recall": round(text_ok / total, 4) if total else None,  # recognized anywhere on the page
        "price_text_recall": round(price_text_ok / price_total, 4) if price_total else None,
        "line_recall": round(found / total, 4) if total else None,  # recognized and located
        "price_line_recall": round(price_found / price_total, 4) if price_total else None,
        "cer_mean": round(statistics.fmean(errors), 4) if errors else None,
        "iou_mean": round(statistics.fmean(ious), 4) if ious else None,
    }
