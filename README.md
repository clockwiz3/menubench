# MenuBench

**English** · [Русский](README.ru.md)

Reading prices off restaurant menus (photos, scans, PDFs) and linking them to a till catalog — built on one rule:
**a wrong price on a screen is worse than an empty slot.** So every system here is scored not only on accuracy, but on
whether it knows which of its answers it can put on a screen without a person checking.

**Result:** letting an LLM link menu items to the catalog directly puts the wrong item on **27%** of links. With a
strong model reading the menu, an independent pipeline checking it, calibrated confidence and a strict linker, wrong
links drop to **1.1%**, and **78%** of prices go on screens unreviewed at **1.1%** errors — with the threshold chosen
on the dev split and only then measured on test. The rest goes to a person, with a hint that has the right catalog
item in the top 3 in 100% of cases.

| approach | pair F1 % | auto-placed % | wrong among auto-placed % | + box off the price % | wrong catalog links % | $/menu |
|---|---|---|---|---|---|---|
| Claude reads, pipeline checks, calibrated (v0.2) | 97.2 | 77.7 | 1.1 | 0.4 | 1.1 | 0.0057 |
| Claude Haiku 5.5, one call | 97.2 | – | – | – | – | 0.0014 |
| reference pipeline, calibrated (v0.1) | 70.6 | 4.8 | 15.3 | 0.5 | 6.1 | 0.0041 |
| reference pipeline + LLM picks the catalog item | 70.6 | 4.8 | 15.3 | 0.5 | 27.1 | 0.0042 |

Synthetic test split: 197 menus, 3 792 prices, 7 layouts (2 unseen during development), clean / scanned / photo-like,
ru and en. **Pair F1** counts a price only if both the value and its item are right. *Auto-placed* — share of all
prices placed without review and correct. A dash — no operating point for that approach.

![Risk–coverage on the synthetic test split](reports/risk_coverage.png)

## How it got here

**v0.1 — a pipeline of cheap calls** (VLM OCR, a crop per price, voting, calibration, strict linking) reached 70.6%
pair F1, and its dev-chosen threshold broke on test: 15% wrong among auto-placed prices against a 1% target. One call
to Claude Haiku read the same menus at 97.2%.

**v0.2 — the strong model reads, the v0.1 pipeline checks.** One call is accurate but cannot tell where it is wrong;
a differently built pipeline fails differently, so their agreement — on the price, the item and where the box is —
becomes the confidence signal; where the pipeline saw no price, it reads that area again without being told what
to expect. Calibrated on dev only, its 1% operating point held on test. v0.2 was designed after
v0.1's test results were known, so the clean check is a hand-labelled golden set of ~50 real menu pages from Serbia and Bosnia,
being collected now ([dataset card](docs/real-dataset.md), [annotation guide](docs/annotation-guide.md)).

## What I learned

1. **Safeguards decide what reaches a screen, not model choice.** Direct LLM linking: 27% wrong links; strict linker
   on prices both opinions trust: 1.1%.
2. **A pipeline of cheap calls lost to one strong call** (70.6% vs 97.2% pair F1).
3. **In-sample calibration is not evidence.** v0.1's calibration error was 0.004 on dev and 0.069 on test.
4. **Disagreement between differently built systems** made a trustworthy threshold possible where the reader's own
   confidence could not set one at all.
5. **Voting only helps against independent errors** (60.3% → 65.7% → 70.6% with a second pass and a tie-breaker).

Full tables, ablations, slices, OCR comparison, design decisions and what did not work:
**[docs/details.md](docs/details.md)**.

## Run it

```bash
uv sync && uv run playwright install chromium
uv run menubench synth --out data/synth -n 300 --seed 42      # the synthetic dataset, regenerated from the seed
cp .env.example .env                                             # OPENROUTER_API_KEY
uv run menubench run configs/second-opinion-claude-cal.yaml --split test --dry-run   # cost estimate
uv run menubench run configs/second-opinion-claude-cal.yaml --split test
uv run menubench report                                          # tables and chart in reports/

cd web && npm ci && npm run build && cd .. && uv run menubench serve   # http://127.0.0.1:8000
```

The web app has a run explorer with per-menu error review, an annotation tool for real photos, and a live demo that
streams the pipeline's stages. Every model response is cached locally, so re-scoring is free and offline
(`--mode replay`). All experiments behind these numbers cost about $10.

## License

MIT