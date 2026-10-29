"""Markdown tables (and later charts) for the README, built from the latest run of every config."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from menubench.runs import RUNS_DIR, RunDir, list_runs

REPORTS_DIR = Path("reports")


def latest_runs(root: Path = RUNS_DIR, prefix: str = "") -> dict[str, tuple[RunDir, dict[str, Any]]]:
    """config name -> (run, metrics) for the most recent evaluated run of each config."""
    out: dict[str, tuple[RunDir, dict[str, Any]]] = {}
    for run in list_runs(root):
        metrics = run.metrics()
        if metrics is None:
            continue
        name = run.info().config_name
        if name.startswith(prefix):
            out[name] = (run, metrics)
    return out


def _pct(v: float | None) -> str:
    return "–" if v is None else f"{v * 100:.1f}"


def _num(v: float | None, digits: int = 2) -> str:
    return "–" if v is None else f"{v:.{digits}f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _model(run: RunDir, role: str) -> str:
    models: dict[str, str] = run.info().config.get("models", {})
    return models.get(role, "–")


def ocr_table(runs: dict[str, tuple[RunDir, dict[str, Any]]]) -> str:
    rows: list[tuple[float, list[str]]] = []
    for run, m in runs.values():
        o = m.get("ocr")
        if not o:
            continue
        rows.append(
            (
                -(o["line_recall"] or 0),
                [
                    f"`{_model(run, 'ocr')}`",
                    _pct(o["text_recall"]),
                    _pct(o["line_recall"]),
                    _pct(o["price_line_recall"]),
                    _num(o["iou_mean"]),
                    _num(o["cer_mean"], 3),
                    f"{m['cost']['per_menu_usd']:.4f}",
                    _num(m["latency_s"]["p50"], 1),
                    str(m["menus"]),
                ],
            )
        )
    headers = ["OCR model", "text found %", "located %", "prices located %", "IoU", "CER", "$/menu", "p50 s", "menus"]
    return _table(headers, [r for _, r in sorted(rows, key=lambda r: r[0])])


def extraction_table(runs: dict[str, tuple[RunDir, dict[str, Any]]]) -> str:
    rows: list[tuple[float, list[str]]] = []
    for name, (_run, m) in runs.items():
        if not m["pred_prices"] and not m.get("failed_menus"):
            continue
        sel = m["selective"]
        rows.append(
            (
                -m["pair"]["f1"],
                [
                    f"`{name}`",
                    _pct(m["price"]["f1"]),
                    _pct(m["pair"]["f1"]),
                    _pct(m["name_accuracy"]),
                    _num(sel["aurc"], 3),
                    _pct(sel["safe_recall"].get("0.01")),
                    _pct(sel["safe_recall"].get("0.05")),
                    f"{m['cost']['per_menu_usd']:.4f}",
                    _num(m["latency_s"]["p50"], 1),
                    str(m["menus"]),
                ],
            )
        )
    headers = [
        "config",
        "price F1 %",
        "pair F1 %",
        "names %",
        "AURC ↓",
        "safe recall @1% risk",
        "@5% risk",
        "$/menu",
        "p50 s",
        "menus",
    ]
    return _table(headers, [r for _, r in sorted(rows, key=lambda r: r[0])])


SECTIONS: dict[str, tuple[str, Callable[[dict[str, tuple[RunDir, dict[str, Any]]]], str]]] = {
    "ocr": ("ocr-", ocr_table),
    "extraction": ("", extraction_table),
}


def write_reports(root: Path = RUNS_DIR, out: Path = REPORTS_DIR) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for kind, (prefix, build) in SECTIONS.items():
        runs = latest_runs(root, prefix)
        if not runs:
            continue
        path = out / f"{kind}.md"
        path.write_text(build(runs) + "\n", encoding="utf-8")
        written.append(path)
    return written
