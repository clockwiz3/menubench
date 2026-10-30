# Annotation guide — real menus

[← README](../README.md) · [Русский](annotation-guide.ru.md) · [Dataset card](real-dataset.md)

Written before labelling the first menu and not changed afterwards; if a rule has to change, every menu labelled
under the old rule is relabelled. The point of a golden set is that menu 1 and menu 50 follow the same rules.

## What to label

**Label only what you can read with certainty at 100% zoom.** Never guess a digit; a skipped price is a smaller
error than a wrong one, exactly as on a screen. If something is skipped because of glare or blur, add the tag
`partially-unreadable`.

| On the menu | Label |
|---|---|
| A dish or drink with its own price | an **item** (its name) and a **price** linked to it |
| Section titles ("Supe", "Салаты", "Drinks") | nothing — they are not items |
| Descriptions, ingredients, allergens | nothing — not part of the name |
| Portion weight or volume as information ("300 g", "0,5 l" next to a single price) | nothing — not a price, not part of the name |
| Several sizes with their own prices ("0,33 l 250 / 0,5 l 350", S/M/L) | one item; one price per size, kind **size variant**, size label exactly as printed |
| Combo or set ("Combo 1: burger + fries + drink 890") | one item named as printed, one price; components are not separate items |
| "Price on request", "po dogovoru", "по запросу", "market price" | the item, no price |
| Item listed without a price because the group has one price ("all pancakes 450") | an item named after the group as printed ("Palačinke"), one price linked to it; the listed variants are not items |
| Crossed-out old price next to a new one | both prices; the old one has kind **crossed** |
| "od 450", "от 450", "from 450" | kind **from**, value 450 |
| "450–650" | kind **range**, value 450, upper bound 650 |
| Add-on surcharges ("+60 din extra cheese"), deposits, delivery fees | nothing — they are not menu items |

## Names

- Exactly as printed: same script (Cyrillic or Latin), case and punctuation as printed. Do not translate, transliterate
  or correct typos.
- A name over several lines is one item; its box covers the whole name block.
- Bilingual menus (Serbian + English): the name is the line in the menu's language (the language chosen at upload);
  the other language is ignored. Tag the menu `bilingual`.

## Prices

- Value as a number: `1.250` on a Serbian menu is **1250** (dot = thousands), `1.250,00` is 1250, `12.50` on a menu in
  euros or dollars is 12.50.
- Currency only if printed next to the price or in the menu header for all prices (`din`, `дин`, `RSD` → RSD).
- The price box is tight around the printed price including its currency mark if it touches it; it does not include
  weights, sizes or dot leaders.

## Tags (slices in reports)

Tick every tag that applies: `printed-pdf`, `photo`, `glare`, `angled`, `low-light`, `chalkboard`, `handwritten`,
`multi-column`, `bilingual`, `cyrillic`, `latin`, `mixed-script`, `laminated`, `sizes`, `combo`,
`partially-unreadable`. Results on real photos are reported per tag.

## Workflow

1. Before uploading, crop or blur anything that is not the menu: people, faces, car plates, receipts.
2. **Annotate** → upload (language Serbian) → **Pre-label with pipeline** → fix every box, name and link → tags →
   **Finish**. Finish is refused while a price has no item.
3. When all menus are finished, fix the split once:
   `uv run menubench real split --dev 20 --seed 7`. Test menus are then not run, not looked at in run review and not
   used for any threshold until the pipeline is frozen. The command refuses to reshuffle afterwards.
4. A week later, relabel five menus without looking at the first labelling:
   `uv run menubench real recheck <id1>,<id2>,<id3>,<id4>,<id5>` creates empty copies; label them in Annotate.
   Then `uv run menubench real agreement` writes the self-agreement to `reports/annotation_agreement.md`.
