# MenuBench

**English** · [Русский](README.ru.md)

Benchmark and reference pipeline for extracting prices from restaurant menus — photos, scans and PDFs.

> A wrong price on a screen is worse than an empty slot.

So the pipeline is allowed to say "not sure" — and it is scored on that. Instead of a single accuracy number,
MenuBench reports a **risk–coverage curve**: how many errors remain among the prices the system decided to label,
at every level of coverage.

**Status:** in development, see [the plan](PLAN.md).

## What it measures

- **Track A — extraction.** Image or PDF in, `{price, currency, item name, box, confidence}` out.
- **Track B — catalog linking with abstention.** Link each price to a POS-style catalog
  (abbreviations, typos, look-alike items, items that are not there) — or return a hint or an abstention with a reason.

Metrics: price and pair F1, name accuracy, selective risk at coverage, AURC, wrong-link rate, $ per menu, p50/p95 latency.

## Pipeline (planned)

```
ingest → VLM OCR → price detection (patterns + geometry) → name attribution (2–3 VLM passes, majority vote)
       → confidence calibration → strict linker → LLM arbiter (suggests, never decides) → link | hint | abstain
```

All models are called through [OpenRouter](https://openrouter.ai). Every response is cached locally, so any
experiment can be replayed offline at zero cost.

## Data

Development runs on a procedural synthetic generator: HTML layouts rendered with Playwright, exact boxes from
the DOM, photo-like augmentations. The pipeline is frozen before real menu photos are collected, so the real
split is an honest held-out test of the synthetic-to-real gap.

## Results so far

Synthetic v0 (clean renders, 22 dev menus, 400 prices). Clean synthetic menus are already saturated by strong VLMs; the hard cases and photo-like augmentations of v1 are what separate the configurations. Full tables: [OCR](reports/ocr.md), [extraction](reports/extraction.md).

| config | price F1 % | pair F1 % | names % | AURC ↓ | safe recall @1% risk | @5% risk | $/menu | p50 s | menus |
|---|---|---|---|---|---|---|---|---|---|
| `e2e-gemini31-flash-lite` | 100.0 | 100.0 | 100.0 | 0.000 | 100.0 | 100.0 | 0.0024 | 3.9 | 22 |
| `e2e-qwen3vl-235b` | 100.0 | 100.0 | 100.0 | 0.000 | 100.0 | 100.0 | 0.0027 | 26.9 | 22 |
| `e2e-claude-haiku55` | 100.0 | 99.8 | 99.8 | 0.001 | 99.8 | 99.8 | 0.0011 | 7.4 | 22 |
| `e2e-gemini25-flash-lite` | 98.4 | 98.1 | 99.8 | 0.032 | 0.0 | 98.8 | 0.0005 | 3.3 | 22 |
| `heuristic-gemini25-flash-lite` | 97.0 | 86.2 | 88.9 | 0.270 | 0.0 | 0.0 | 0.0007 | 4.5 | 22 |
| `e2e-qwen3vl-8b` | 75.2 | 74.8 | 99.3 | 0.189 | 0.0 | 0.0 | 0.0012 | 11.9 | 22 |

## Quick start

```bash
uv sync
uv run menubench --help
uv run pytest
```

Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` for live runs.

## Web app

```bash
cd web && npm ci && npm run build && cd ..
uv run menubench serve          # http://127.0.0.1:8000
```

- **Runs** — leaderboard over every evaluated run, per-run metrics, risk–coverage curve, slices.
- **Menu review** — the page with ground truth, predictions colored by outcome (correct, wrong item, old price,
  not on the menu, missed), OCR lines and the raw output of every pipeline stage.

For frontend development run `npm run dev` in `web/` next to `menubench serve`; TypeScript types for the API
are generated from the FastAPI schema (`menubench openapi` → `npm run gen:api`).

## License

MIT
