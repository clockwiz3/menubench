"""README tables and charts, built from the latest run of every config on one split (test by default)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from menubench.runs import RUNS_DIR, RunDir, list_runs

REPORTS_DIR = Path("reports")
Runs = dict[str, tuple[RunDir, dict[str, Any]]]

# Configs shown in the headline chart, in a fixed order so each keeps its color across reports.
CHART_CONFIGS = ("e2e-claude-haiku55", "e2e-gemini25-flash-lite", "full-gemini25-flash-lite-cal")


def latest_runs(root: Path = RUNS_DIR, prefix: str = "", split: str = "test") -> Runs:
    """config name -> (run, metrics) for the most recent evaluated run of each config on `split`."""
    out: Runs = {}
    for run in list_runs(root):
        metrics = run.metrics()
        if metrics is None:
            continue
        info = run.info()
        if info.split == split and info.config_name.startswith(prefix):
            out[info.config_name] = (run, metrics)
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


def ocr_table(runs: Runs) -> str:
    rows: list[tuple[float, list[str]]] = []
    for run, m in runs.values():
        o = m.get("ocr")
        if not o or m.get("pred_prices"):
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


def extraction_table(runs: Runs) -> str:
    rows: list[tuple[float, list[str]]] = []
    for name, (_run, m) in runs.items():
        if name.startswith("ablation-") or (not m["pred_prices"] and not m.get("failed_menus")):
            continue
        sel = m["selective"]
        op = m.get("operating_point") or {}
        rows.append(
            (
                -m["pair"]["f1"],
                [
                    f"`{name}`",
                    _pct(m["price"]["f1"]),
                    _pct(m["pair"]["f1"]),
                    _num(sel["aurc"], 3),
                    _num((m.get("calibration") or {}).get("ece"), 3),
                    _pct(op.get("recall")),
                    _pct(op.get("risk")),
                    f"{m['cost']['per_menu_usd']:.4f}",
                    _num(m["latency_s"]["p50"], 1),
                    str(m["menus"]) + (f" ({m['failed_menus']} failed)" if m.get("failed_menus") else ""),
                ],
            )
        )
    headers = [
        "config",
        "price F1 %",
        "pair F1 %",
        "AURC ↓",
        "ECE ↓",
        "auto-placed %",
        "wrong among auto-placed %",
        "$/menu",
        "p50 s",
        "menus",
    ]
    return _table(headers, [r for _, r in sorted(rows, key=lambda r: r[0])])


def linking_table(runs: Runs) -> str:
    rows = []
    for name, (_run, m) in sorted(runs.items()):
        lk = m.get("linking")
        if not lk or name.startswith("ablation-"):
            continue
        d = lk["decisions"]
        rows.append(
            [
                f"`{name}`",
                str(lk["links"]),
                _pct(lk["wrong_link_rate"]),
                _pct(lk["auto_link_recall"]),
                _pct(lk["hint_top3"]),
                _pct(lk["abstain_precision"]),
                str(d.get("link_wrong", 0)),
            ]
        )
    headers = [
        "config",
        "links",
        "wrong links % ↓",
        "linked automatically %",
        "hint has answer (top-3) %",
        "abstentions justified %",
        "wrong prices on screens",
    ]
    return _table(headers, rows)


def ablation_table(runs: Runs) -> str:
    names = [
        n
        for n in ("full-gemini25-flash-lite-cal", "ablation-no-tiebreak", "ablation-1pass", "full-gemini25-flash-lite")
        if n in runs
    ]
    labels = {
        "full-gemini25-flash-lite-cal": "full: 2 passes + tie-break, calibrated",
        "ablation-no-tiebreak": "no third pass on disagreement",
        "ablation-1pass": "single pass",
        "full-gemini25-flash-lite": "hand-set confidence instead of calibration",
    }
    rows = []
    for n in names:
        m = runs[n][1]
        op = m.get("operating_point") or {}
        rows.append(
            [
                labels[n],
                _pct(m["pair"]["f1"]),
                _num(m["selective"]["aurc"], 3),
                _num((m.get("calibration") or {}).get("ece"), 3),
                _pct(op.get("recall")),
                _pct(op.get("risk")),
                f"{m['cost']['per_menu_usd']:.4f}",
            ]
        )
    return _table(["variant", "pair F1 %", "AURC ↓", "ECE ↓", "auto-placed %", "wrong among auto %", "$/menu"], rows)


def slices_table(runs: Runs, config: str = "full-gemini25-flash-lite-cal") -> str:
    if config not in runs:
        config = next((c for c in CHART_CONFIGS if c in runs), "")
    if not config:
        return ""
    m = runs[config][1]
    rows = []
    for dim in ("augment", "template", "lang"):
        for key, s in m["slices"].get(dim, {}).items():
            label = f"{dim} = {key}" + (" (held out)" if key in ("price_left", "tv_landscape") else "")
            rows.append([label, str(s["menus"]), str(s["gt_prices"]), _pct(s["price"]["f1"]), _pct(s["pair"]["f1"])])
    return f"`{config}`\n\n" + _table(["slice", "menus", "prices", "price F1 %", "pair F1 %"], rows)


def risk_coverage_chart(runs: Runs, path: Path) -> Path | None:
    """Static PNG of the headline curves for the README (the web app has the interactive version)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # The first few kept predictions are a handful of points: their risk is noise, so the chart starts at 3%.
    series = [
        (name, [p for p in runs[name][1]["selective"]["curve"] if p["coverage"] >= 0.03])
        for name in CHART_CONFIGS
        if name in runs
    ]
    if not series:
        return None
    colors = ("#2a78d6", "#eb6834", "#1baf7a")  # categorical slots 1-3, validated for CVD separation
    fig, ax = plt.subplots(figsize=(7.2, 4.0), dpi=150)
    fig.patch.set_facecolor("#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    for (name, curve), color in zip(series, colors, strict=False):
        xs = [p["coverage"] for p in curve]
        ys = [p["risk"] for p in curve]
        ax.step(xs, ys, where="post", color=color, linewidth=2, label=name)
    ax.axhline(0.01, color="#c3c2b7", linewidth=1, linestyle="--")
    ax.text(0.005, 0.012, "1% risk", color="#52514e", fontsize=8)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, max(0.05, max(max(p["risk"] for p in c) for _, c in series if c) * 1.1))
    ax.set_xlabel("coverage — share of predictions kept, most confident first", color="#52514e", fontsize=9)
    ax.set_ylabel("risk — errors among kept", color="#52514e", fontsize=9)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.grid(color="#e1e0d9", linewidth=0.8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors="#52514e", labelsize=8, length=0)
    ax.legend(frameon=False, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=len(series))
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


SECTIONS: dict[str, tuple[str, Callable[[Runs], str]]] = {
    "ocr": ("ocr-", ocr_table),
    "extraction": ("", extraction_table),
    "linking": ("", linking_table),
    "ablations": ("", ablation_table),
    "slices": ("", slices_table),
}


def write_reports(root: Path = RUNS_DIR, out: Path = REPORTS_DIR, split: str = "test") -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for kind, (prefix, build) in SECTIONS.items():
        runs = latest_runs(root, prefix, split)
        table = build(runs) if runs else ""
        path = out / f"{kind}.md"
        if not table:
            continue
        path.write_text(table + "\n", encoding="utf-8")
        written.append(path)
    chart = risk_coverage_chart(latest_runs(root, "", split), out / "risk_coverage.png")
    if chart:
        written.append(chart)
    return written
