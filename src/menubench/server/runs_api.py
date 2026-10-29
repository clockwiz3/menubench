"""Read-only API over run directories: leaderboard, run details, per-menu review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from menubench.data import Dataset
from menubench.eval.match import match_menu
from menubench.runs import RunDir, list_runs
from menubench.schema import MenuPrediction
from menubench.server.schemas import MenuReview, MenuRow, PredictionView, RunDetail, RunSummary

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _root(request: Request) -> Path:
    root: Path = request.app.state.settings.runs_root
    return root


def _run(request: Request, run_id: str) -> RunDir:
    for run in list_runs(_root(request)):
        if run.run_id == run_id:
            return run
    raise HTTPException(404, f"run {run_id} not found")


def summarize(run: RunDir) -> RunSummary:
    info = run.info()
    m: dict[str, Any] = run.metrics() or {}
    sel = m.get("selective") or {}
    safe = sel.get("safe_recall") or {}
    ocr = m.get("ocr") or {}
    return RunSummary(
        run_id=info.run_id,
        config_name=info.config_name,
        pipeline=str(info.config.get("pipeline", "")),
        models=dict(info.config.get("models", {})),
        dataset=info.dataset,
        split=info.split,
        started_at=info.started_at,
        menus=info.menus,
        errors=info.errors,
        cost_usd=info.cost_usd,
        price_f1=(m.get("price") or {}).get("f1"),
        pair_f1=(m.get("pair") or {}).get("f1"),
        name_accuracy=m.get("name_accuracy"),
        aurc=sel.get("aurc"),
        safe_recall_1=safe.get("0.01"),
        safe_recall_5=safe.get("0.05"),
        ocr_text_recall=ocr.get("text_recall"),
        ocr_line_recall=ocr.get("line_recall"),
        per_menu_usd=(m.get("cost") or {}).get("per_menu_usd"),
        latency_p50=(m.get("latency_s") or {}).get("p50"),
        has_prices=bool(m.get("pred_prices")),
        ece=(m.get("calibration") or {}).get("ece"),
        auto_recall=(m.get("operating_point") or {}).get("recall"),
        auto_risk=(m.get("operating_point") or {}).get("risk"),
        wrong_link_rate=(m.get("linking") or {}).get("wrong_link_rate"),
        hint_top3=(m.get("linking") or {}).get("hint_top3"),
    )


@router.get("", response_model=list[RunSummary])
def list_all(request: Request) -> list[RunSummary]:
    return [summarize(r) for r in reversed(list_runs(_root(request))) if r.metrics() is not None]


@router.get("/{run_id}", response_model=RunDetail)
def detail(request: Request, run_id: str) -> RunDetail:
    run = _run(request, run_id)
    info = run.info()
    metrics = run.metrics() or {}
    index = {r.menu_id: r for r in Dataset(Path(info.dataset)).index}
    menus = [
        MenuRow(
            menu_id=menu_id,
            template=index[menu_id].template if menu_id in index else None,
            lang=index[menu_id].lang if menu_id in index else None,
            **row,
        )
        for menu_id, row in (metrics.get("per_menu") or {}).items()
    ]
    metrics = {k: v for k, v in metrics.items() if k != "per_menu"}
    return RunDetail(summary=summarize(run), config=info.config, metrics=metrics, menus=menus)


def _predictions(run: RunDir) -> dict[str, MenuPrediction]:
    return {p.menu_id: p for p in run.predictions()}


@router.get("/{run_id}/menus/{menu_id}", response_model=MenuReview)
def review(request: Request, run_id: str, menu_id: str) -> MenuReview:
    run = _run(request, run_id)
    dataset = Dataset(Path(run.info().dataset))
    predictions = _predictions(run)
    if menu_id not in predictions:
        raise HTTPException(404, f"menu {menu_id} is not part of run {run_id}")
    annotation = dataset.annotation(menu_id)
    prediction = predictions[menu_id]
    match = match_menu(annotation, prediction)
    names = {i.id: i.name for i in annotation.items}
    gt_by_id = {p.id: p for p in annotation.prices}
    outcomes = [
        PredictionView(
            index=pm.pred_index,
            outcome=pm.outcome,
            gt_id=pm.gt_id,
            gt_name=", ".join(names[i] for i in gt_by_id[pm.gt_id].item_ids) if pm.gt_id else None,
            iou=pm.iou,
        )
        for pm in match.matches
    ]
    order = list(predictions)
    pos = order.index(menu_id)
    return MenuReview(
        run_id=run_id,
        menu_id=menu_id,
        annotation=annotation,
        prediction=prediction,
        outcomes=outcomes,
        missed=list(match.missed),
        trace=run.trace(menu_id),
        prev_menu=order[pos - 1] if pos > 0 else None,
        next_menu=order[pos + 1] if pos + 1 < len(order) else None,
    )


@router.get("/{run_id}/menus/{menu_id}/pages/{page}", response_class=FileResponse)
def page_image(request: Request, run_id: str, menu_id: str, page: int) -> FileResponse:
    run = _run(request, run_id)
    dataset = Dataset(Path(run.info().dataset))
    if menu_id not in dataset.ids():  # also guards against path traversal through menu_id
        raise HTTPException(404, "unknown menu")
    annotation = dataset.annotation(menu_id)
    if not 0 <= page < len(annotation.pages):
        raise HTTPException(404, "unknown page")
    return FileResponse(dataset.page_path(annotation, page))
