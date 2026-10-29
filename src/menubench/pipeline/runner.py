"""Runs a pipeline configuration over a dataset split and records everything in a run directory."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from PIL import Image
from pydantic import BaseModel, ConfigDict

from menubench.data import Dataset
from menubench.llm import CacheMode, LLMClient, ResponseCache, UsageMeter
from menubench.llm.models import resolve
from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.runs import RUNS_DIR, RunDir, RunInfo, git_sha, new_run_id
from menubench.schema import MenuAnnotation, MenuPrediction

MODELS_CACHE = Path(".cache/openrouter-models.json")


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    pipeline: str
    dataset: str = "data/synth"
    split: str = "dev"
    limit: int | None = None
    models: dict[str, str]
    params: dict[str, Any] = {}
    budget_usd: float | None = 2.0
    concurrency: int = 4  # menus in flight
    llm_concurrency: int = 16  # model calls in flight across all menus

    @classmethod
    def load(cls, path: Path) -> RunConfig:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def pipelines() -> dict[str, type[Pipeline]]:
    from menubench.pipeline.baselines import OcrHeuristic, VlmEndToEnd
    from menubench.pipeline.full import FullPipeline
    from menubench.pipeline.ocr_only import OcrOnly

    return {p.name: p for p in (OcrOnly, VlmEndToEnd, OcrHeuristic, FullPipeline)}


def build_pipeline(cfg: RunConfig, client: LLMClient) -> Pipeline:
    try:
        cls = pipelines()[cfg.pipeline]
    except KeyError:
        raise ValueError(f"unknown pipeline {cfg.pipeline!r}; known: {', '.join(pipelines())}") from None
    return cls(client, cfg.models, cfg.params)


def load_pages(dataset: Dataset, annotation: MenuAnnotation) -> list[Image.Image]:
    pages = []
    for i in range(len(annotation.pages)):
        with Image.open(dataset.page_path(annotation, i)) as img:
            pages.append(img.convert("RGB"))
    return pages


async def process_menu(pipeline: Pipeline, menu: MenuInput, log: StageLog, config_name: str) -> MenuPrediction:
    started = time.perf_counter()
    try:
        prediction = await pipeline.process(menu, log)
        return prediction.model_copy(update={"config": config_name})
    except Exception as exc:
        await log.stage("error", message=f"{type(exc).__name__}: {exc}")
        return MenuPrediction(
            menu_id=menu.menu_id,
            config=config_name,
            error=f"{type(exc).__name__}: {exc}"[:500],
            latency_s=time.perf_counter() - started,
        )


async def run_config(
    cfg: RunConfig,
    *,
    mode: CacheMode = CacheMode.RECORD_MISSING,
    runs_root: Path = RUNS_DIR,
    on_menu: Any = None,
) -> RunDir:
    dataset = Dataset(Path(cfg.dataset))
    menu_ids = dataset.ids(cfg.split, cfg.limit)
    run = RunDir(runs_root / new_run_id(cfg.name))
    info = RunInfo(
        run_id=run.run_id,
        config_name=cfg.name,
        config=cfg.model_dump(),
        dataset=cfg.dataset,
        split=cfg.split,
        started_at=datetime.now(UTC),
        git_sha=git_sha(),
    )
    run.write_info(info)
    (run.path / "predictions.jsonl").write_text("", encoding="utf-8")

    cache = ResponseCache()
    client = LLMClient(cache=cache, mode=mode, meter=UsageMeter(cfg.budget_usd), concurrency=cfg.llm_concurrency)
    pipeline = build_pipeline(cfg, client)
    sem = asyncio.Semaphore(cfg.concurrency)

    async def one(menu_id: str) -> MenuPrediction:
        async with sem:
            annotation = dataset.annotation(menu_id)
            menu = MenuInput(menu_id, load_pages(dataset, annotation), catalog=annotation.catalog)
            log = StageLog()
            prediction = await process_menu(pipeline, menu, log, cfg.name)
            run.append_prediction(prediction)
            run.write_trace(menu_id, log.trace)
            if on_menu:
                on_menu(menu_id)
            return prediction

    try:
        predictions = await asyncio.gather(*(one(m) for m in menu_ids))
    finally:
        await client.aclose()
        cache.close()

    info.finished_at = datetime.now(UTC)
    info.menus = len(predictions)
    info.cost_usd = round(sum(p.cost_usd for p in predictions), 6)
    info.errors = sum(p.error is not None for p in predictions)
    run.write_info(info)
    return run


def _pricing() -> dict[str, tuple[float, float]]:
    """$ per token (input, output) from the public OpenRouter model list, cached for a day."""
    if not MODELS_CACHE.exists() or time.time() - MODELS_CACHE.stat().st_mtime > 86400:
        MODELS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        MODELS_CACHE.write_bytes(httpx.get("https://openrouter.ai/api/v1/models", timeout=30).content)
    data = json.loads(MODELS_CACHE.read_text(encoding="utf-8"))["data"]
    return {m["id"]: (float(m["pricing"].get("prompt") or 0), float(m["pricing"].get("completion") or 0)) for m in data}


def estimate_cost(cfg: RunConfig) -> dict[str, Any]:
    """Rough upper-bound estimate: image tokens from pixels after downscale, output from line counts."""
    dataset = Dataset(Path(cfg.dataset))
    pricing = _pricing()
    client = LLMClient(api_key="dry-run")
    pipeline = build_pipeline(cfg, client)
    per_role: dict[str, float] = {}
    menus = dataset.ids(cfg.split, cfg.limit)
    for menu_id in menus:
        ann = dataset.annotation(menu_id)
        for role, calls, image_share, out_tokens in pipeline.estimate_calls(len(ann.pages), len(ann.prices) or 30):
            spec = pipeline.models[role]
            page = ann.pages[0]
            scale = min(1.0, spec.max_image_side / max(page.width, page.height))
            image_tokens = page.width * page.height * scale * scale / 784 * image_share + 300
            p_in, p_out = pricing.get(spec.id, (0.0, 0.0))
            per_role[role] = per_role.get(role, 0.0) + calls * (image_tokens * p_in + out_tokens * p_out)
    return {
        "menus": len(menus),
        "per_role_usd": {k: round(v, 4) for k, v in per_role.items()},
        "total_usd": round(sum(per_role.values()), 4),
        "models": {role: resolve(m).id for role, m in cfg.models.items()},
    }
