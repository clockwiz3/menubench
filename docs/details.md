# MenuBench — details

[← README](../README.md) · [Русский](details.ru.md)

## Results in detail

### Track A — extraction

| config | price F1 % | pair F1 % | AURC ↓ | ECE ↓ | auto-placed % | wrong among auto-placed % | $/menu | p50 s | menus |
|---|---|---|---|---|---|---|---|---|---|
| `e2e-claude-haiku55` | 98.7 | 97.2 | 0.007 | 0.086 | – | – | 0.0014 | 10.7 | 197 |
| `second-opinion-claude-cal` | 98.7 | 97.2 | 0.008 | 0.077 | 77.7 | 1.1 | 0.0057 | 6.8 | 197 |
| `e2e-qwen3vl-235b` | 94.0 | 92.7 | 0.052 | 0.043 | – | – | 0.0029 | 35.3 | 197 |
| `e2e-gemini31-flash-lite` | 93.7 | 92.4 | 0.063 | 0.038 | – | – | 0.0026 | 5.2 | 197 |
| `e2e-gemini25-flash-lite` | 93.6 | 90.1 | 0.076 | 0.085 | – | – | 0.0005 | 4.8 | 197 |
| `e2e-qwen3vl-8b` | 81.0 | 78.3 | 0.243 | 0.213 | – | – | 0.0012 | 14.4 | 197 |
| `full-gemini31-attr-cal` | 87.1 | 73.4 | 0.111 | 0.045 | 0.0 | – (n=3) | 0.0164 | 30.0 | 197 |
| `full-gemini25-flash-lite-cal` | 86.2 | 70.6 | 0.153 | 0.069 | 4.8 | 15.3 | 0.0041 | 30.0 | 197 |
| `full-gemini25-flash-lite` | 86.2 | 70.6 | 0.155 | 0.101 | – | – | 0.0036 | 6.5 | 197 |
| `full-gemini25-flash-lite-linkdirect` | 86.2 | 70.6 | 0.153 | 0.069 | 4.8 | 15.3 | 0.0042 | 9.8 | 197 |
| `heuristic-gemini25-flash-lite` | 85.5 | 31.8 | 0.548 | 0.207 | – | – | 0.0008 | 1.4 | 197 |

`auto-placed` and `wrong among auto-placed` use the threshold frozen on dev for a 1% target; "– (n=3)" means too
few auto-placed prices for a rate. AURC is the area under the risk–coverage curve, ECE the expected calibration error.
Latency of `second-opinion-claude-cal` was measured on cached calls; live, it is the slower of its two parts (~30 s).

### Track B — catalog linking

| config | links | wrong links % ↓ | linked automatically % | hint has answer (top-3) % | abstentions justified % | wrong prices on screens |
|---|---|---|---|---|---|---|
| `full-gemini25-flash-lite` | 2390 | 13.9 | 93.2 | 99.2 | 96.8 | 331 |
| `full-gemini25-flash-lite-cal` | 163 | 6.1 | 6.9 | 99.8 | 96.8 | 10 |
| `full-gemini25-flash-lite-linkdirect` | 2933 | 27.1 | 96.8 | – | 99.1 | 794 |
| `full-gemini31-attr-cal` | 3 | – (n=3) | 0.0 | 100.0 | 96.8 | 3 |
| `second-opinion-claude-cal` | 2395 | 1.1 | 74.8 | 100.0 | 96.2 | 27 |

### Ablations of the v0.1 pipeline

| variant | pair F1 % | AURC ↓ | ECE ↓ | auto-placed % | wrong among auto % | $/menu |
|---|---|---|---|---|---|---|
| full: 2 passes + tie-break, calibrated | 70.6 | 0.153 | 0.069 | 4.8 | 15.3 | 0.0041 |
| no third pass on disagreement | 65.7 | 0.175 | 0.117 | 4.8 | 15.3 | 0.0037 |
| single pass | 60.3 | 0.257 | 0.201 | 6.3 | 20.8 | 0.0025 |
| hand-set confidence instead of calibration | 70.6 | 0.155 | 0.101 | – | – | 0.0036 |

### Where the v0.1 pipeline breaks

`full-gemini25-flash-lite-cal`

| slice | menus | prices | price F1 % | pair F1 % |
|---|---|---|---|---|
| augment = clean | 44 | 845 | 97.6 | 87.7 |
| augment = photo | 80 | 1520 | 74.3 | 47.8 |
| augment = scan | 73 | 1427 | 91.1 | 82.8 |
| template = cards_grid | 28 | 566 | 89.0 | 78.5 |
| template = chalkboard | 28 | 549 | 90.1 | 84.0 |
| template = classic_columns | 29 | 576 | 84.1 | 69.6 |
| template = narrow_stand | 28 | 547 | 90.4 | 80.6 |
| template = price_left (held out) | 28 | 563 | 87.8 | 52.7 |
| template = sizes_table | 28 | 482 | 80.4 | 57.8 |
| template = tv_landscape (held out) | 28 | 509 | 80.4 | 69.0 |
| lang = en | 94 | 1729 | 91.4 | 74.6 |
| lang = ru | 103 | 2063 | 81.6 | 67.0 |

### OCR (60 test menus)

| OCR model | text found % | located % | prices located % | IoU | CER | $/menu | p50 s | menus |
|---|---|---|---|---|---|---|---|---|
| `qwen/qwen3-vl-235b-a22b-instruct` | 99.1 | 90.2 | 89.3 | 0.59 | 0.007 | 0.0044 | 42.1 | 60 |
| `google/gemini-3.1-flash-lite` | 99.5 | 90.1 | 88.7 | 0.65 | 0.016 | 0.0037 | 5.9 | 60 |
| `google/gemini-2.5-flash-lite` | 97.7 | 88.7 | 91.7 | 0.66 | 0.031 | 0.0008 | 1.4 | 60 |
| `qwen/qwen3-vl-8b-instruct` | 98.2 | 74.9 | 66.7 | 0.44 | 0.047 | 0.0017 | 35.8 | 60 |
| `anthropic/claude-haiku-5.5` | 98.4 | 67.2 | 68.9 | 0.59 | 0.066 | 0.0014 | 9.9 | 60 |

## What it measures

- **Track A — extraction.** Image or PDF in, `{price, currency, item, box, confidence}` out. Matching is one-to-one
  by value and position; a price counts for pair F1 only with the right item name (normalized, CER ≤ 0.15).
  Crossed-out old prices reported as current count as errors.
- **Track B — catalog linking with abstention.** Each price is linked to a till-style catalog (abbreviations,
  typos, transliteration, codes, look-alike items, items that are not there) — or gets a hint or an abstention with
  a reason. Wrong links are the headline: they are wrong prices on screens.
- Selective prediction: risk–coverage, AURC, safe recall at 1/2/5% risk, ECE, and the frozen operating point.
- Cost ($/menu from OpenRouter usage accounting) and latency (p50/p95).

## Pipelines

v0.1, the verifier:

```
VLM OCR (tiles, native box format) → price candidates (patterns, inline prices, phone/weight guards)
  → item attribution: crop with the price outlined in red + nearby OCR lines, 2 passes, 3rd on disagreement
  → signals (agreement, model confidence, geometry, placement, column alignment)
  → calibration (logistic + isotonic, dev only) → auto-place or review
  → strict catalog linker → LLM arbiter re-ranks hints, never links → link | hint | abstain
```

v0.2, second opinion: Claude Haiku 5.5 reads the whole menu in one call; v0.1 runs independently on the same
image; per price: did the verifier find the same price, the same item, how sure was each → calibrated
confidence → auto-place or review → strict linking for trusted prices only.

## Data

- **Synthetic generator** (`menubench synth`): ru/en content from hand-written vocabularies, 7 HTML layouts
  rendered in headless Chromium, exact per-line boxes from DOM ranges; hard cases (crossed-out prices, "from",
  ranges, weights, size grids, long descriptions, distractor notes); scan and photo degradations as homographies
  plus lighting, glare, blur, noise and JPEG, with boxes moved through the same transform; a POS catalog per menu.
  Two layouts (price-left, TV landscape) appear only in test.
- **Real photos:** collected after the freeze and labelled in the web annotator; the frozen pipeline then runs on
  them once (`menubench run <config> --dataset data/real --split real-test`).

## Decisions and trade-offs

- **Clean room.** No code, prompts or data from any employer; different providers than in production work.
- **VLM as OCR, chosen by measurement.** Boxes are requested in each model's native convention (`bbox_2d` 0–1000,
  `box_2d` y-first), structured output where supported, and malformed JSON is salvaged instead of failing a menu.
- **Recognition and localization are scored separately**, because they fail differently.
- **Confidence is learned, thresholds are frozen.** Calibration and thresholds are fitted on dev only; the CLI
  refuses to calibrate on any other split. Test measures what the frozen threshold does — which is how finding 2
  became visible.
- **The arbiter cannot link.** An LLM may re-order and explain hints; only the deterministic linker links, and only
  for prices the pipeline trusts.
- **Held-out layouts stayed held out.** The price-left failure was visible in the annotator before the final run;
  it was not fixed, so the test numbers stay honest.
- **Pixel-exact boxes where people look.** Model boxes drift by a glyph; the demo and the annotator's pre-labelling
  snap each price box to its ink (line segmentation, color of the price's own ink, word count of the printed price),
  falling back to the model's box when the result looks implausible. Benchmark scores keep raw boxes: the synthetic
  ground truth is the typographic line box, so snapping to ink would lower IoU without changing any decision.
- **Reproducibility without publishing model outputs.** Every response is cached locally by
  (model, prompt version, parameters, image hash); `--mode replay` re-scores everything offline. The cache is not
  published; `--dry-run` estimates what a fresh run costs.

## What did not work

- Assuming that a pipeline of cheap calls beats one strong call (finding 2).
- Trusting in-sample calibration (finding 3).
- Majority voting against correlated errors (finding 5).
- Geometry-only attribution on photographed pages (finding 6).
- Qwen3-VL-30B, GPT-5-nano and Mistral Small as OCR: they read text but place boxes half a line off or worse.

## What I would do next

- Rotation-aware crops for the verifier: on tilted photos its up-and-left crop reads the name from the row
  above, so it disagrees with a correct reader and sends good prices to review (safe, but costs automation).
- Real photos: re-check the v0.2 operating point, and compare the verifier signal with the reader's own confidence.
- A cheaper verifier: the full v0.1 pipeline is more than a second opinion needs.
- Calibrate on data that matches deployment (real photos), add image-quality features (blur, perspective) and a
  "layout looks new" detector that forces review.
- Conformal risk control instead of a single frozen threshold, with a separate calibration split.
- Symmetric crops (names to the right of prices exist).