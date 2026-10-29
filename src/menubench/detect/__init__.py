"""Price candidates and simple geometry over OCR lines."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from menubench.prices import ParsedPrice, parse_price, split_trailing_price
from menubench.schema import BBox, TextLine

_SIZE_LABEL = re.compile(
    r"^(?:[SMLX]{1,2}L?|small|medium|large|малая|средняя|большая|\d+(?:[.,]\d+)?\s?(?:см|мл|л|oz|cm|ml|l|\")|\d+\")$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    line: int  # index into the OCR lines
    parsed: ParsedPrice
    text: str
    bbox: BBox
    merged_name: str | None = None  # name found on the same OCR line ("Борщ .... 350")


def is_size_label(text: str) -> bool:
    return bool(_SIZE_LABEL.match(text.strip()))


def find_candidates(lines: list[TextLine]) -> list[Candidate]:
    out = []
    for i, line in enumerate(lines):
        parsed = parse_price(line.text)
        if parsed is not None:
            out.append(Candidate(i, parsed, line.text, line.bbox))
            continue
        split = split_trailing_price(line.text)
        if split is not None:
            name, parsed = split
            # The price sits at the right end of a merged line; approximate its box by text share.
            share = max(0.15, min(0.5, (len(line.text) - len(name)) / max(len(line.text), 1)))
            b = line.bbox
            box = BBox(x0=b.x1 - (b.x1 - b.x0) * share, y0=b.y0, x1=b.x1, y1=b.y1)
            # "25 см 1 150 р.": the head is a size label, not a dish name.
            out.append(Candidate(i, parsed, line.text, box, merged_name=None if is_size_label(name) else name))
    return out


def v_overlap(a: BBox, b: BBox) -> float:
    """Vertical overlap relative to the shorter box."""
    inter = min(a.y1, b.y1) - max(a.y0, b.y0)
    return max(0.0, inter) / max(min(a.y1 - a.y0, b.y1 - b.y0), 1e-9)


def h_overlap(a: BBox, b: BBox) -> float:
    inter = min(a.x1, b.x1) - max(a.x0, b.x0)
    return max(0.0, inter) / max(min(a.x1 - a.x0, b.x1 - b.x0), 1e-9)


def median_height(lines: list[TextLine]) -> float:
    return statistics.median([line.bbox.y1 - line.bbox.y0 for line in lines]) if lines else 0.02
