# Dataset card — MenuBench real menus

[← README](../README.md) · [Annotation guide](annotation-guide.md)

**Status:** being collected. Numbers below are filled in when the set is finished. The Hugging Face card for the release is drafted in [`hf/README.md`](../hf/README.md).

| | |
|---|---|
| What | ~50 menu pages from restaurants, cafés and street food: phone photos of printed menus and screenshots of menus published online; labelled by hand: every readable price, the item it belongs to, boxes for both |
| Where | Serbia (Novi Sad) and Bosnia and Herzegovina |
| Languages | Serbian (Latin and Cyrillic), English, often mixed on one menu |
| Currency | Serbian dinar (RSD: `1.250` is one thousand two hundred fifty) and convertible mark (KM, BAM) |
| Splits | ~20 `real-dev` / ~30 `real-test` by **venue**: all pages of one place stay on one side; venues already seen while tuning are pinned to dev; assigned once (`menubench real split --dev 20 --seed 7`) and locked; test is used only after the pipeline is frozen |
| Slices | per-menu tags: printed PDF, photo, glare, angled, low light, chalkboard, handwritten, multi-column, bilingual, script, laminated, sizes, combos |
| Annotation | one annotator (the author), [written guide](annotation-guide.md) fixed before the first menu, pipeline pre-labelling corrected by hand |
| Report | `menubench report --split real-dev` (or `real-test`, once) writes `reports/<split>/real.md`: what the split holds, each approach's pair F1 and auto-placed share with errors among them, synthetic vs real, and the same per tag and per venue |
| Self-agreement | five menus relabelled blind a week later: *to be measured* (`reports/annotation_agreement.md`) |

## Collection and privacy

Images collected by the author from publicly displayed menus (in Serbia and Bosnia and Herzegovina) and from menus
published on the venues' websites, for non-commercial research. No personal
data: people, faces and anything else that is not the menu are cropped or blurred before upload. Menus photographed
inside a venue are taken with the staff's permission.

**If you own a menu in this set and want it removed, open an issue** and it will be taken out.

## License

The images and their annotations: [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). The code of this
repository stays under MIT. The menus' text and design remain the property of their owners.

## Known limitations

- Few venues, one annotator: the agreement figure measures consistency, not correctness against a second person.
- Menus were chosen for variety, not sampled at random, so slice sizes do not reflect how common each layout is.
- v0.2 of the pipeline was designed after its synthetic test results were known, and its name-agreement rule came
  from looking at a few real photos uploaded to the demo; those menus are not part of this set.
