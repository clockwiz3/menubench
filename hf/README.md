---
pretty_name: MenuBench Real Menus
license: cc-by-nc-4.0
language:
  - sr
  - bs
  - en
task_categories:
  - object-detection
  - image-to-text
tags:
  - menu
  - price-extraction
  - document-understanding
  - ocr
  - vlm-evaluation
  - selective-prediction
  - digital-signage
size_categories:
  - n<1K
configs:
  - config_name: photos
    data_files:
      - split: dev
        path: photos/dev/metadata.jsonl
      - split: test
        path: photos/test/metadata.jsonl
  - config_name: online
    data_files:
      - split: dev
        path: online/dev.jsonl
      - split: test
        path: online/test.jsonl
---

# MenuBench Real Menus

> **Draft.** The set is still being annotated; counts marked *TBD* are filled in when the split is fixed.

A small, hand-labelled golden set of real restaurant menus from Serbia and Bosnia and Herzegovina: every readable
price, the menu item it belongs to, and a box for both. It is the real-photo half of
[MenuBench](https://github.com/clockwiz3/menubench), a benchmark for reading menu prices with vision-language models
when **a wrong price on a screen is worse than an empty slot**: models are scored not only on what they read, but on
how many prices they can place unattended while staying under a fixed error rate.

## At a glance

| | |
|---|---|
| Menus / pages | *TBD* (~50 pages) |
| Venues | *TBD* (cafés, restaurants, street food) |
| Prices / items | *TBD* |
| Splits | `dev` ~20 pages, `test` ~30 pages, split **by venue** |
| Configs | `photos`: phone photos, images included · `online`: menus published on venues' websites, annotations and source links only |
| Languages | Serbian (Latin and Cyrillic), Bosnian, English; often two on one menu |
| Currencies | RSD (dinar) and BAM (convertible mark, printed as KM) |

## What makes it hard

- **Photos, not scans**: angled shots, glare on laminated pages, low light, two-page spreads with a spiral binding.
- **Number formats**: `1.250` is one thousand two hundred fifty dinars, `12,50 KM` is twelve and a half marks;
  prices sit next to weights (`350 g`) and sizes (`0,33 l / 0,5 l`) that are not prices.
- **Layout**: dot leaders, multi-column pages, the same dish printed twice (Serbian and English halves),
  one price per group of items, allergen marks next to names.

## Data fields

One row per menu page.

| Field | Type | Meaning |
|---|---|---|
| `menu_id` | string | Stable id, e.g. `real-20261030-ea321b` |
| `page` | int | Page number within the menu, from 0 |
| `venue_id` | string | Opaque venue id (`v01`, `v02`, …); all pages of one venue share it and stay in one split |
| `file_name` | image | The page, re-encoded without EXIF (`photos` only) |
| `source_url` | string | Where the menu is published (`online` only); the image is not redistributed |
| `width`, `height` | int | Page size in pixels |
| `lang` | string | Language the item names are taken from (BCP 47) |
| `tags` | list[string] | Hard-case markers, see below |
| `items` | list | `{id, name, bbox}`: the item name exactly as printed |
| `prices` | list | `{id, value, value_max, currency, kind, size_label, bbox, item_ids}` |

- `bbox` is `[x0, y0, x1, y1]`, relative to the page (0..1).
- `value` and `value_max` are decimal strings (`"1250"`, `"12.50"`); `value_max` is set only for ranges.
- `currency` is ISO 4217 (`RSD`, `BAM`) when printed next to the price or once for the whole menu, otherwise null.
- `kind`: `single`, `size_variant` (one of several sizes, with `size_label` as printed), `range`, `from`
  (`od 450`), `crossed` (an old, struck-through price that must never be shown as current).
- `item_ids` links a price to its item(s); a group price links to the group's name.

Tags: `photo`, `screenshot`, `printed-pdf`, `glare`, `angled`, `low-light`, `chalkboard`, `handwritten`,
`multi-column`, `bilingual`, `cyrillic`, `latin`, `mixed-script`, `laminated`, `sizes`, `combo`,
`partially-unreadable`.

## Loading

```python
from datasets import load_dataset

photos = load_dataset("<hf-user>/menubench-real-menus", "photos", split="dev")
page = photos[0]
page["image"], page["prices"][0]
```

For `online`, the image is fetched from `source_url` at the stated size; the
[MenuBench repository](https://github.com/clockwiz3/menubench) has the loader and the evaluation code.

## Evaluation

The intended use is evaluation, with the protocol from the MenuBench repository:

- predicted prices are matched one to one with labelled ones by value and position;
- **pair F1** counts a price as right only when it is linked to the right item;
- **risk–coverage**: a system also says which prices it would place without review; the report gives the share placed
  unattended and the error rate among them, plus how often a right price's box misses the printed price;
- thresholds are fitted on `dev` only. `test` is meant to be run once per frozen system; please do not tune on it.

Baseline results on this set: *TBD* (the MenuBench README will carry them once `test` has been run).

## Annotation

- One annotator (the dataset author), following a [written guide](https://github.com/clockwiz3/menubench/blob/main/docs/annotation-guide.md)
  fixed before the first menu: only what is readable at 100% zoom is labelled, digits are never guessed.
- Pages were pre-labelled by a model pipeline and every box, name and link corrected by hand.
- Self-agreement: five pages relabelled blind a week later: *TBD*. It measures consistency, not agreement with a
  second person.

## Collection, privacy and removal

Images collected by the author from publicly displayed menus (in Serbia and Bosnia and Herzegovina) and from menus
published on the venues' websites, for non-commercial research. People, faces, licence plates, receipts and anything
else that is not the menu are cropped or blurred before release. Menus photographed inside a venue were taken with
the staff's permission. Menus published online are not redistributed: the set holds their annotations and a link.

**If you own a menu in this set and want it removed, open a discussion on this page or an issue in the
[GitHub repository](https://github.com/clockwiz3/menubench/issues)**, and it will be taken out.

## Limitations

- Small: about fifty pages from a handful of venues in two countries; slice sizes are too small for tight confidence
  intervals, and the report shows counts instead of rates below 20 events.
- Chosen for variety, not sampled at random, so the mix of layouts does not reflect how common each one is.
- One annotator.
- Links in `online` can rot; a page that changes or disappears drops out of the set.

## License

Annotations and the released images: [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). The menus'
text and design remain the property of their owners. The MenuBench code is MIT.

## Citation

```bibtex
@misc{menubench2026,
  title  = {MenuBench: reading menu prices with VLMs when a wrong price is worse than none},
  author = {<author>},
  year   = {2026},
  url    = {https://github.com/clockwiz3/menubench}
}
```
