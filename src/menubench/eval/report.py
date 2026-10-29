"""Human-readable summaries of metrics dictionaries."""

from __future__ import annotations

from typing import Any


def _pct(value: float | None) -> str:
    return "  -  " if value is None else f"{value * 100:5.1f}%"


def format_summary(m: dict[str, Any]) -> str:
    sel = m["selective"]
    safe = sel["safe_recall"]
    lines = [
        f"run        {m.get('run_id', '-')}",
        f"menus      {m['menus']}  (failed: {m.get('failed_menus', 0)})",
        f"prices     gt {m['gt_prices']}  predicted {m['pred_prices']}",
        f"price      P {_pct(m['price']['precision'])}  R {_pct(m['price']['recall'])}  F1 {_pct(m['price']['f1'])}",
        f"pair       P {_pct(m['pair']['precision'])}  R {_pct(m['pair']['recall'])}  F1 {_pct(m['pair']['f1'])}",
        f"names      {_pct(m['name_accuracy'])} of found prices have the right item",
        f"bbox IoU   {m['bbox_iou_mean'] if m['bbox_iou_mean'] is not None else '-'}",
        f"selective  AURC {sel['aurc'] if sel['aurc'] is not None else '-'}   safe recall "
        + "  ".join(f"@{float(k) * 100:g}% {_pct(v)}" for k, v in safe.items()),
        f"cost       ${m['cost']['total_usd']:.4f} total, ${m['cost']['per_menu_usd']:.5f}/menu",
        f"latency    p50 {m['latency_s']['p50']}s  p95 {m['latency_s']['p95']}s",
    ]
    for dim in ("template", "lang", "augment"):
        for key, s in m["slices"].get(dim, {}).items():
            lines.append(
                f"  {dim}={key:<15} n={s['menus']:<4} price F1 {_pct(s['price']['f1'])} pair F1 {_pct(s['pair']['f1'])}"
            )
    return "\n".join(lines)
