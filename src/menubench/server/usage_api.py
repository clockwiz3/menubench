"""Model usage statistics for this machine: spend, requests, tokens and local cache savings by day and model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from menubench.llm import ResponseCache

router = APIRouter(prefix="/api/usage", tags=["usage"])


class UsageSummary(BaseModel):
    days: list[str]
    models: list[str]
    series: dict[str, dict[str, dict[str, float]]]  # day -> model -> metric -> value
    by_model: list[dict[str, Any]]
    by_source: list[dict[str, Any]]


@router.get("", response_model=UsageSummary)
def summary(days: int = Query(30, ge=1, le=365)) -> UsageSummary:
    cache = ResponseCache()
    try:
        return UsageSummary.model_validate(cache.summary(days))
    finally:
        cache.close()
