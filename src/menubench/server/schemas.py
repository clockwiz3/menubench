"""API response models. Core schema types are reused as-is so the frontend sees the same shapes as the files."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from menubench.eval.match import Outcome
from menubench.schema import MenuAnnotation, MenuPrediction


class RunSummary(BaseModel):
    run_id: str
    config_name: str
    pipeline: str
    models: dict[str, str]
    dataset: str
    split: str
    started_at: datetime
    menus: int
    errors: int
    cost_usd: float
    price_f1: float | None = None
    pair_f1: float | None = None
    name_accuracy: float | None = None
    aurc: float | None = None
    safe_recall_1: float | None = None
    safe_recall_5: float | None = None
    ocr_text_recall: float | None = None
    ocr_line_recall: float | None = None
    per_menu_usd: float | None = None
    latency_p50: float | None = None
    has_prices: bool = False


class MenuRow(BaseModel):
    menu_id: str
    template: str | None = None
    lang: str | None = None
    gt: int
    pred: int
    tp: int
    pair_tp: int
    errors: int
    cost_usd: float
    latency_s: float


class RunDetail(BaseModel):
    summary: RunSummary
    config: dict[str, Any]
    metrics: dict[str, Any]
    menus: list[MenuRow]


class PredictionView(BaseModel):
    index: int
    outcome: Outcome
    gt_id: str | None
    gt_name: str | None
    iou: float | None


class MenuReview(BaseModel):
    run_id: str
    menu_id: str
    annotation: MenuAnnotation
    prediction: MenuPrediction | None
    outcomes: list[PredictionView]
    missed: list[str]
    trace: dict[str, Any] | None
    prev_menu: str | None
    next_menu: str | None
