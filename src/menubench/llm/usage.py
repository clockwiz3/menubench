"""Call journal and usage statistics: every model call, paid or served from the local cache.

Lives in the cache database. History from before the journal existed is rebuilt from the cached responses
(one row per distinct live call), so spend since the first experiment is visible.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

SCHEMA = """create table if not exists calls (
    id integer primary key autoincrement,
    ts text not null,
    model text not null,
    source text not null default '',
    cached integer not null,
    cost_usd real not null,
    latency_s real not null,
    prompt_tokens integer not null default 0,
    completion_tokens integer not null default 0,
    reasoning_tokens integer not null default 0,
    provider_cached_tokens integer not null default 0)"""


@dataclass(frozen=True)
class Tokens:
    prompt: int = 0
    completion: int = 0
    reasoning: int = 0
    provider_cached: int = 0


def tokens_from(body: dict[str, Any]) -> Tokens:
    """OpenRouter usage block; reasoning and provider-side prompt caching sit in the details objects."""
    usage = body.get("usage") or {}
    completion_details = usage.get("completion_tokens_details") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    return Tokens(
        prompt=int(usage.get("prompt_tokens") or 0),
        completion=int(usage.get("completion_tokens") or 0),
        reasoning=int(completion_details.get("reasoning_tokens") or 0),
        provider_cached=int(prompt_details.get("cached_tokens") or 0),
    )


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(SCHEMA)
    db.execute("create index if not exists calls_ts on calls (ts)")
    if db.execute("select count(*) from calls").fetchone()[0] == 0:
        backfill(db)
    db.commit()


def backfill(db: sqlite3.Connection) -> int:
    """One journal row per cached response: the calls that were actually paid for before the journal existed."""
    rows = db.execute("select model, response, cost_usd, latency_s, created_at from responses").fetchall()
    for model, response, cost, latency, created in rows:
        try:
            body = json.loads(response)
        except ValueError:
            body = {}
        t = tokens_from(body)
        ts = (created or "").replace(" ", "T") + "+00:00" if created else datetime.now(UTC).isoformat()
        db.execute(
            "insert into calls (ts, model, source, cached, cost_usd, latency_s, prompt_tokens, completion_tokens,"
            " reasoning_tokens, provider_cached_tokens) values (?, ?, 'history', 0, ?, ?, ?, ?, ?, ?)",
            (ts, model, cost or 0.0, latency or 0.0, t.prompt, t.completion, t.reasoning, t.provider_cached),
        )
    return len(rows)


def record(
    db: sqlite3.Connection, model: str, source: str, cached: bool, cost: float, latency: float, body: dict[str, Any]
) -> None:
    t = tokens_from(body)
    db.execute(
        "insert into calls (ts, model, source, cached, cost_usd, latency_s, prompt_tokens, completion_tokens,"
        " reasoning_tokens, provider_cached_tokens) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            datetime.now(UTC).isoformat(),
            model,
            source,
            int(cached),
            cost,
            latency,
            t.prompt,
            t.completion,
            t.reasoning,
            t.provider_cached,
        ),
    )
    db.commit()


def summarize(db: sqlite3.Connection, days: int = 30, today: date | None = None) -> dict[str, Any]:
    """Per day and model: live spend, requests, tokens; plus what the local cache served and saved."""
    today = today or datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        "select substr(ts, 1, 10) as day, model, source, cached, count(*), sum(cost_usd), sum(latency_s),"
        " sum(prompt_tokens), sum(completion_tokens), sum(reasoning_tokens), sum(provider_cached_tokens)"
        " from calls where substr(ts, 1, 10) >= ? group by day, model, source, cached",
        (start.isoformat(),),
    ).fetchall()
    days_list = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    per_day: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    by_model: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_source: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for day, model, source, cached, n, cost, latency, prompt, completion, reasoning, provider_cached in rows:
        bucket = per_day[day][model]
        target = by_model[model]
        src = by_source[source or "unknown"]
        if cached:
            for d in (bucket, target, src):
                d["cache_hits"] += n
                d["saved_usd"] += cost or 0.0
            continue
        for d in (bucket, target, src):
            d["requests"] += n
            d["cost_usd"] += cost or 0.0
            d["prompt_tokens"] += prompt or 0
            d["completion_tokens"] += (completion or 0) - (reasoning or 0)
            d["reasoning_tokens"] += reasoning or 0
            d["provider_cached_tokens"] += provider_cached or 0
        target["latency_s"] += latency or 0.0

    def clean(d: dict[str, float]) -> dict[str, float]:
        return {k: round(v, 6) if isinstance(v, float) else v for k, v in d.items()}

    models = sorted(by_model, key=lambda m: -(by_model[m]["cost_usd"] + by_model[m]["saved_usd"]))
    return {
        "days": days_list,
        "models": models,  # stable order by total spend: the same model keeps the same color everywhere
        "series": {day: {m: clean(v) for m, v in per_day[day].items()} for day in days_list if day in per_day},
        "by_model": [
            {
                "model": m,
                **clean(by_model[m]),
                "avg_latency_s": round(by_model[m]["latency_s"] / by_model[m]["requests"], 3)
                if by_model[m]["requests"]
                else None,
            }
            for m in models
        ],
        "by_source": sorted(
            ({"source": s, **clean(v)} for s, v in by_source.items()), key=lambda r: -float(r.get("cost_usd", 0))
        ),
    }
