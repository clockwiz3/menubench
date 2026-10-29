"""POS-style catalogs for track B: the same dishes as the menu, spelled the way a till spells them."""

from __future__ import annotations

import random
from collections.abc import Callable

from menubench.schema import CatalogEntry
from menubench.synth.content import MenuContent
from menubench.synth.lexicon import VOCAB

_TRANSLIT = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        "a|b|v|g|d|e|e|zh|z|i|y|k|l|m|n|o|p|r|s|t|u|f|kh|ts|ch|sh|sch||y||e|yu|ya".split("|"),
        strict=True,
    )
)


def translit(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in _TRANSLIT:
            t = _TRANSLIT[low]
            out.append(t.capitalize() if ch.isupper() else t)
        else:
            out.append(ch)
    return "".join(out)


def _abbreviate(name: str, rng: random.Random) -> str:
    words = name.split()
    return " ".join(w if len(w) <= 5 or i == 0 else w[: rng.randint(3, 4)] + "." for i, w in enumerate(words))


def _typo(name: str, rng: random.Random) -> str:
    letters = [i for i, ch in enumerate(name) if ch.isalpha()]
    if len(letters) < 4:
        return name
    i = rng.choice(letters[1:-1])
    if rng.random() < 0.5:
        return name[:i] + name[i + 1 :]  # dropped letter
    return name[:i] + name[i + 1] + name[i] + name[i + 2 :]  # swapped neighbours


def _reorder(name: str, rng: random.Random) -> str:
    words = name.split()
    return " ".join(words[1:] + words[:1]) if len(words) > 1 else name


def _code(name: str, rng: random.Random) -> str:
    return f"{rng.choice(['KX', 'BAR', 'ГОР', 'ХОЛ', 'DR'])}-{rng.randint(1, 999):03d} {name}"


def _portion(name: str, rng: random.Random) -> str:
    return f"{name} {rng.choice(['250г', '300г', '1 порц', '0.3л', '1шт', '12oz'])}"


TRANSFORMS: dict[str, Callable[[str, random.Random], str]] = {
    "upper": lambda n, r: n.upper(),
    "abbrev": _abbreviate,
    "typo": _typo,
    "reorder": _reorder,
    "code": _code,
    "portion": _portion,
}


def pos_name(name: str, lang: str, rng: random.Random) -> str:
    out = name
    for key in rng.sample(sorted(TRANSFORMS), k=rng.randint(1, 2)):
        out = TRANSFORMS[key](out, rng)
    if lang == "ru" and rng.random() < 0.15:
        out = translit(out)
    return out


def make_catalog(
    content: MenuContent, rng: random.Random, absent_rate: float = 0.15, distractors: tuple[int, int] = (3, 7)
) -> tuple[tuple[CatalogEntry, ...], dict[str, str | None]]:
    """Returns (catalog, item id -> catalog id or None when the item is missing from the till)."""
    sections, _ = VOCAB[content.lang]
    names: list[tuple[str | None, str]] = []
    mapping: dict[str, str | None] = {}
    for item in content.items():
        if rng.random() < absent_rate:
            mapping[item.id] = None
            continue
        names.append((item.id, pos_name(item.name, content.lang, rng)))

    # Hard negatives: same base with another modifier, or another dish from the same kind of section.
    on_menu = {i.name for i in content.items()}
    pool = sorted(
        {f"{b} {m}" for v in sections.values() for b in v.bases for m in v.modifiers}
        | {b for v in sections.values() for b in v.bases}
    )
    menu_bases = {i.name.split()[0] for i in content.items()}
    similar = [p for p in pool if p.split()[0] in menu_bases and p not in on_menu]
    other = [p for p in pool if p not in on_menu]
    count = rng.randint(*distractors)
    picks = rng.sample(similar, k=min(len(similar), count // 2 + 1)) + rng.sample(other, k=count // 2)
    names += [(None, pos_name(p, content.lang, rng)) for p in picks]

    rng.shuffle(names)
    entries = []
    for n, (item_id, text) in enumerate(names, start=1):
        cid = f"c{n:03d}"
        entries.append(CatalogEntry(id=cid, name=text))
        if item_id:
            mapping[item_id] = cid
    return tuple(entries), mapping
