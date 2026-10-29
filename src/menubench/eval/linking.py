"""Track B scoring: what each link decision would do to a screen.

A link to the wrong catalog item puts a wrong price on a screen, so `wrong_link_rate` is the headline number.
Hints and abstentions cost operator time, not correctness; they are scored for usefulness.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from menubench.eval.match import MenuMatch, Outcome
from menubench.schema import MenuAnnotation, MenuPrediction

ABSENT = "absent"  # the menu item is not in the till
SPURIOUS = "spurious"  # the price itself does not exist on the menu


def _truth(annotation: MenuAnnotation, gt_id: str | None, outcome: Outcome) -> str | None:
    """Catalog id the prediction should link to, ABSENT, or SPURIOUS."""
    if gt_id is None or outcome is Outcome.SPURIOUS:
        return SPURIOUS
    price = next(p for p in annotation.prices if p.id == gt_id)
    items = {i.id: i for i in annotation.items}
    if outcome is Outcome.WRONG_NAME:
        return SPURIOUS  # the right price under the wrong item: any link would be wrong
    cid = items[price.item_ids[0]].catalog_id
    return cid if cid else ABSENT


def evaluate_linking(
    triples: Iterable[tuple[MenuAnnotation, MenuPrediction, MenuMatch]],
) -> dict[str, Any] | None:
    counts: Counter[str] = Counter()
    linkable = 0
    any_links = False
    for ann, pred, match in triples:
        if not pred.links:
            continue
        any_links = True
        for pm in match.matches:
            decision = pred.links[pm.pred_index]
            truth = _truth(ann, pm.gt_id, pm.outcome)
            if truth not in (ABSENT, SPURIOUS):
                linkable += 1
            if decision is None or decision.action == "abstain":
                counts["abstain_right" if truth in (ABSENT, SPURIOUS) else "abstain_missed"] += 1
            elif decision.action == "link":
                counts["link_right" if decision.catalog_id == truth else "link_wrong"] += 1
            else:
                top = [c.catalog_id for c in decision.candidates[:3]]
                if truth in (ABSENT, SPURIOUS):
                    counts["hint_no_target"] += 1
                else:
                    counts["hint_useful" if truth in top else "hint_useless"] += 1
    if not any_links:
        return None
    links = counts["link_right"] + counts["link_wrong"]
    hints_with_target = counts["hint_useful"] + counts["hint_useless"]
    abstains = counts["abstain_right"] + counts["abstain_missed"]
    return {
        "decisions": dict(counts),
        "links": links,
        "wrong_link_rate": round(counts["link_wrong"] / links, 4) if links else None,
        "auto_link_recall": round(counts["link_right"] / linkable, 4) if linkable else None,
        "hint_top3": round(counts["hint_useful"] / hints_with_target, 4) if hints_with_target else None,
        "abstain_precision": round(counts["abstain_right"] / abstains, 4) if abstains else None,
        "linkable": linkable,
    }
