# MenuBench

**English** · [Русский](README.ru.md)

Benchmark and reference pipeline for extracting prices from restaurant menus — photos, scans and PDFs.

> A wrong price on a screen is worse than an empty slot.

So the pipeline is allowed to say "not sure" — and it is scored on that. Instead of a single accuracy number,
MenuBench reports a **risk–coverage curve**: how many errors remain among the prices the system decided to label,
at every level of coverage.

**Status:** early development (milestone M0 of [the plan](PLAN.md)). No results yet.

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

## Quick start

```bash
uv sync
uv run menubench --help
uv run pytest
```

Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY` for live runs.

## License

MIT
