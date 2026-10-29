"""Text normalization and distances used for every name and OCR comparison."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz.distance import Levenshtein

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Case, ё/е, quotes, punctuation and whitespace do not count as recognition errors."""
    text = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    text = _PUNCT.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def cer(predicted: str, reference: str) -> float:
    """Character error rate on normalized text, relative to the reference length."""
    p, r = normalize(predicted), normalize(reference)
    if not r:
        return 0.0 if not p else 1.0
    return Levenshtein.distance(p, r) / len(r)


def similar(predicted: str | None, references: list[str], max_cer: float = 0.15) -> bool:
    if not predicted:
        return False
    return any(cer(predicted, ref) <= max_cer for ref in references if ref)
