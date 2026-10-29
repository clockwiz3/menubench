"""Model access: OpenRouter client, response cache, prompts, JSON parsing and box conventions."""

from __future__ import annotations

import functools
import json
import re
from importlib import resources
from typing import Any

from menubench.llm.cache import CacheMiss, CacheMode, ResponseCache
from menubench.llm.client import ImagePart, LLMClient, LLMError, LLMResponse, UsageMeter, load_dotenv

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


@functools.cache
def prompt(name: str) -> tuple[str, str]:
    """Returns (text, version) for `prompts/<name>.md`; the version is the `vN` suffix of the file name."""
    files = resources.files("menubench.prompts")
    matches = sorted(f.name for f in files.iterdir() if f.name.startswith(f"{name}.v") and f.name.endswith(".md"))
    if not matches:
        raise FileNotFoundError(f"prompt {name} not found")
    latest = matches[-1]
    version = latest.removeprefix(f"{name}.").removesuffix(".md")
    return files.joinpath(latest).read_text(encoding="utf-8"), f"{name}.{version}"


def parse_json(text: str) -> Any:
    """Models wrap JSON in fences or prose; take the fenced block or the outermost object/array."""
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text
    candidate = candidate.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (candidate.find("{"), candidate.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON found in model output")
    start = min(starts)
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    return json.loads(candidate[start : end + 1])


__all__ = [
    "CacheMiss",
    "CacheMode",
    "ImagePart",
    "LLMClient",
    "LLMError",
    "LLMResponse",
    "ResponseCache",
    "UsageMeter",
    "load_dotenv",
    "parse_json",
    "prompt",
]
