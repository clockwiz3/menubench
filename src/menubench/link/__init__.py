"""Track B: link a menu item to a till catalog, or hand the operator a hint, or abstain.

A link is only made when it is unambiguous; everything uncertain becomes a hint with an explanation.
The LLM arbiter re-ranks and explains hints but never turns a hint into a link.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from menubench.eval.text import normalize
from menubench.llm import LLMClient, parse_json, prompt
from menubench.llm.models import ModelSpec
from menubench.schema import CatalogEntry, LinkCandidate, LinkDecision
from menubench.synth.catalog import translit

_CODE = re.compile(r"^\s*[A-Za-zА-Яа-яЁё]{1,4}-\d{2,4}\s+")
_PORTION = re.compile(r"\s+\d+(?:[.,]\d+)?\s?(?:г|гр|g|мл|ml|л|l|oz|шт|порц)\.?(?=\s|$)", re.IGNORECASE)


def canon(text: str) -> str:
    """Till spelling and menu spelling meet here: no codes, no portions, latin letters, no punctuation."""
    text = _CODE.sub("", text)
    text = _PORTION.sub("", text)
    return translit(normalize(text))


def similarity(menu_name: str, catalog_name: str) -> float:
    a, b = canon(menu_name), canon(catalog_name)
    if not a or not b:
        return 0.0
    whole = fuzz.token_sort_ratio(a, b) / 100
    # Abbreviations: "солянка сбор." matches "солянка сборная" word by word through prefixes.
    wa, wb = a.split(), b.split()
    matched = sum(1 for w in wb if any((len(w) >= 3 and x.startswith(w)) or fuzz.ratio(w, x) >= 85 for x in wa))
    by_words = matched / max(len(wa), len(wb))
    return round(max(whole, by_words), 4)


@dataclass(frozen=True)
class LinkerConfig:
    link_at: float = 0.9  # minimal similarity for an automatic link
    margin: float = 0.08  # and the runner-up must be at least this much worse
    hint_at: float = 0.55  # below this the catalog has nothing similar: abstain
    top_k: int = 3


def rank(name: str, catalog: tuple[CatalogEntry, ...]) -> list[LinkCandidate]:
    scored = [LinkCandidate(catalog_id=c.id, score=similarity(name, c.name)) for c in catalog]
    return sorted(scored, key=lambda c: -c.score)


def decide(
    name: str | None, catalog: tuple[CatalogEntry, ...], cfg: LinkerConfig, price_trusted: bool = True
) -> LinkDecision:
    if not name:
        return LinkDecision(action="abstain", reason="the item name was not recognized")
    if not catalog:
        return LinkDecision(action="abstain", reason="the catalog is empty")
    ranked = rank(name, catalog)
    best = ranked[0]
    second = ranked[1].score if len(ranked) > 1 else 0.0
    top = tuple(c for c in ranked[: cfg.top_k] if c.score >= cfg.hint_at / 2)
    if best.score < cfg.hint_at:
        return LinkDecision(action="abstain", reason=f"no similar item in the catalog (best match {best.score:.0%})")
    if best.score >= cfg.link_at and best.score - second >= cfg.margin:
        if price_trusted:
            return LinkDecision(action="link", catalog_id=best.catalog_id, candidates=top)
        return LinkDecision(
            action="hint",
            candidates=top,
            reason="the catalog match is clear, but the price or item on the menu is uncertain",
        )
    if best.score >= cfg.link_at:
        reason = f"two catalog items are almost equally similar ({best.score:.0%} and {second:.0%})"
    else:
        reason = f"closest catalog item is only {best.score:.0%} similar"
    return LinkDecision(action="hint", candidates=top, reason=reason)


async def arbitrate(
    client: LLMClient, spec: ModelSpec, name: str, price: str, decision: LinkDecision, catalog: tuple[CatalogEntry, ...]
) -> tuple[LinkDecision, float]:
    """Asks an LLM to order the hint's candidates and explain. Returns (decision, cost). Never links."""
    if decision.action != "hint" or not decision.candidates:
        return decision, 0.0
    names = {c.id: c.name for c in catalog}
    text, version = prompt("arbiter")
    listing = "\n".join(f"- {c.catalog_id}: {names[c.catalog_id]}" for c in decision.candidates)
    response = await client.complete(
        spec.id,
        text.replace("{{ITEM}}", name).replace("{{PRICE}}", price).replace("{{CANDIDATES}}", listing),
        prompt_version=version,
        fallback_models=spec.fallback,
        max_tokens=300,
    )
    try:
        data: Any = parse_json(response.text)
    except ValueError:
        return decision, response.cost_usd
    if not isinstance(data, dict):
        return decision, response.cost_usd
    reason = str(data.get("reason") or decision.reason or "")[:300]
    if data.get("none_match") is True:
        return LinkDecision(
            action="abstain", candidates=decision.candidates, reason=f"arbiter: {reason}"
        ), response.cost_usd
    order = [str(i) for i in data.get("ranking") or [] if str(i) in {c.catalog_id for c in decision.candidates}]
    by_id = {c.catalog_id: c for c in decision.candidates}
    reordered = tuple(by_id[i] for i in order) + tuple(c for c in decision.candidates if c.catalog_id not in order)
    return LinkDecision(action="hint", candidates=reordered, reason=f"arbiter: {reason}"), response.cost_usd


async def link_direct(
    client: LLMClient, spec: ModelSpec, name: str | None, catalog: tuple[CatalogEntry, ...]
) -> tuple[LinkDecision, float]:
    """Baseline: the LLM picks a catalog id and is trusted blindly. Shows what skipping the safeguards costs."""
    if not name or not catalog:
        return LinkDecision(action="abstain", reason="no item name or empty catalog"), 0.0
    text, version = prompt("link_direct")
    listing = "\n".join(f"- {c.id}: {c.name}" for c in catalog)
    response = await client.complete(
        spec.id,
        text.replace("{{ITEM}}", name).replace("{{CATALOG}}", listing),
        prompt_version=version,
        fallback_models=spec.fallback,
        max_tokens=100,
    )
    try:
        data: Any = parse_json(response.text)
        chosen = str(data.get("catalog_id") or "") if isinstance(data, dict) else ""
    except ValueError:
        chosen = ""
    if chosen in {c.id for c in catalog}:
        return LinkDecision(action="link", catalog_id=chosen), response.cost_usd
    return LinkDecision(action="abstain", reason="the model found no match"), response.cost_usd
