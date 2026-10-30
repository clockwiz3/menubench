"""Annotation self-agreement: the same person labels the same menu twice, blind, a week apart."""

from __future__ import annotations

from typing import Any

from menubench.data.real import FINISHED, RealStore
from menubench.eval.match import Outcome, match_menu
from menubench.schema import MenuAnnotation, MenuPrediction, PricePrediction


def _as_prediction(second: MenuAnnotation, menu_id: str) -> MenuPrediction:
    names = {i.id: i.name for i in second.items}
    prices = tuple(
        PricePrediction(
            page=p.page,
            value=p.value,
            value_max=p.value_max,
            currency=p.currency,
            kind=p.kind,
            bbox=p.bbox,
            name=", ".join(names[i] for i in p.item_ids) or None,
            confidence=1.0,
        )
        for p in second.prices
    )
    return MenuPrediction(menu_id=menu_id, config="recheck", prices=prices)


def self_agreement(store: RealStore) -> dict[str, Any]:
    """First labelling is the reference, the blind recheck is scored against it like a prediction."""
    rows: list[dict[str, int | str]] = []
    counts: list[tuple[int, int, int, int]] = []  # gt, relabelled, same price, same item
    for menu_id in store.ids():
        recheck = f"{menu_id}-recheck"
        if recheck not in store.ids() or store.meta(recheck).status.value not in FINISHED:
            continue
        first = store.annotation(menu_id)
        match = match_menu(first, _as_prediction(store.annotation(recheck), menu_id))
        found = match.tp
        same_item = sum(m.outcome is Outcome.CORRECT for m in match.matches)
        counts.append((match.gt_current, len(match.matches), found, same_item))
        rows.append(
            {
                "menu_id": menu_id,
                "prices": match.gt_current,
                "relabelled": len(match.matches),
                "same_price": found,
                "same_item": same_item,
            }
        )
    gt = sum(c[0] for c in counts)
    second = sum(c[1] for c in counts)
    same_price = sum(c[2] for c in counts)
    same = sum(c[3] for c in counts)
    return {
        "menus": len(rows),
        "prices": gt,
        # F1 between two labellings: both missing and extra prices count against agreement.
        "pair_agreement": round(2 * same / (gt + second), 4) if gt + second else None,
        "price_agreement": round(2 * same_price / (gt + second), 4) if gt + second else None,
        "per_menu": rows,
    }
