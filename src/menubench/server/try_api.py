"""Public demo: upload a menu, watch the pipeline work stage by stage (SSE), get prices with decisions.

Abuse and cost guards: per-IP daily limit, a daily dollar ceiling for all visitors together, file size cap,
uploads deleted after 24 hours. The API key never reaches the browser. Without a key or budget the demo
still serves the gallery of precomputed examples.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import shutil
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from menubench.data.real import UploadError, pages_from_upload
from menubench.llm import LLMClient, LLMError, ResponseCache, UsageMeter
from menubench.pipeline.base import MenuInput, StageLog
from menubench.pipeline.runner import RunConfig, build_pipeline
from menubench.schema import MenuPrediction, Page

router = APIRouter(prefix="/api/try", tags=["try"])
MAX_UPLOAD = 10 * 1024 * 1024
KEEP_SECONDS = 24 * 3600
GALLERY_DIR = Path(__file__).parent / "gallery"


class TryPage(BaseModel):
    index: int
    width: int
    height: int
    url: str


class TryJob(BaseModel):
    job_id: str
    status: str  # running | done | failed
    pages: list[TryPage]
    prediction: MenuPrediction | None = None
    error: str | None = None
    created_at: datetime


class TryLimits(BaseModel):
    enabled: bool
    reason: str | None
    uploads_left_today: int
    budget_left_usd: float


class GalleryItem(BaseModel):
    id: str
    title: str
    note: str
    job: TryJob


@dataclass
class Job:
    job_id: str
    folder: Path
    pages: list[Page]
    created_at: datetime
    status: str = "running"
    prediction: MenuPrediction | None = None
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        self.changed.set()


@dataclass
class TryState:
    jobs: dict[str, Job] = field(default_factory=dict)
    by_ip: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    spend_day: str = ""
    spend_usd: float = 0.0


def _settings(request: Request) -> Any:
    return request.app.state.settings


def _state(request: Request) -> TryState:
    state: TryState | None = getattr(request.app.state, "try_state", None)
    if state is None:
        state = TryState()
        request.app.state.try_state = state
    return state


def _client_ip(request: Request) -> str:
    if _settings(request).trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def limits(request: Request) -> TryLimits:
    settings, state = _settings(request), _state(request)
    if state.spend_day != _today():
        state.spend_day, state.spend_usd = _today(), 0.0
    window = state.by_ip[_client_ip(request)]
    while window and time.time() - window[0] > 86400:
        window.popleft()
    left = max(0, settings.try_uploads_per_ip - len(window))
    budget = max(0.0, settings.try_daily_budget_usd - state.spend_usd)
    reason = None
    if not os.environ.get("OPENROUTER_API_KEY"):
        reason = "live runs are off on this server; the gallery still works"
    elif budget <= 0:
        reason = "today's demo budget is used up; try the gallery or come back tomorrow"
    elif left == 0:
        reason = "you have used today's uploads; the gallery still works"
    return TryLimits(enabled=reason is None, reason=reason, uploads_left_today=left, budget_left_usd=round(budget, 4))


def _cleanup(root: Path, state: TryState) -> None:
    if not root.exists():
        return
    now = time.time()
    for folder in root.iterdir():
        if folder.is_dir() and now - folder.stat().st_mtime > KEEP_SECONDS:
            shutil.rmtree(folder, ignore_errors=True)
            state.jobs.pop(folder.name, None)


def _view(job: Job, base: str) -> TryJob:
    return TryJob(
        job_id=job.job_id,
        status=job.status,
        pages=[
            TryPage(index=p.index, width=p.width, height=p.height, url=f"{base}/{job.job_id}/pages/{p.index}")
            for p in job.pages
        ],
        prediction=job.prediction,
        error=job.error,
        created_at=job.created_at,
    )


def _summary(stage: str, data: dict[str, Any]) -> dict[str, Any]:
    """The event stream carries counts, not payloads: OCR lines and raw model output stay on the server."""
    if stage == "ocr":
        return {"lines": len(data.get("lines", []))}
    if stage == "detect":
        return {"candidates": len(data.get("candidates", []))}
    if stage == "attribution":
        decisions = data.get("decisions", [])
        return {
            "decided": len(decisions),
            "rejected": sum(d.get("status") in ("not_price", "old_price") for d in decisions),
        }
    if stage == "e2e":
        return {"prices": len(data.get("prices", []))}
    if stage == "second_opinion":
        return {k: data.get(k) for k in ("agreed", "reader_only", "verifier_prices")}
    if stage == "price":
        return {k: data.get(k) for k in ("done", "total", "item")}
    if stage == "error":
        return {"message": data.get("message")}
    return {}


async def _run(job: Job, cfg: RunConfig, state: TryState) -> None:
    started = time.perf_counter()
    cache = ResponseCache()
    client = LLMClient(cache=cache, meter=UsageMeter(budget_usd=0.05), concurrency=cfg.llm_concurrency)

    async def emit(stage: str, data: dict[str, Any]) -> None:
        job.push({"stage": stage, "t": round(time.perf_counter() - started, 2), **_summary(stage, data)})

    try:
        pipeline = build_pipeline(cfg, client)
        images = []
        for page in job.pages:
            from PIL import Image

            with Image.open(job.folder / page.image) as img:
                images.append(img.convert("RGB"))
        prediction = await pipeline.process(MenuInput(job.job_id, images), StageLog(emit=emit))
        job.prediction = prediction.model_copy(update={"lines": ()})  # OCR lines are bulky and not needed in the UI
        job.status = "done"
        state.spend_usd += prediction.cost_usd
        job.push(
            {
                "stage": "done",
                "t": round(time.perf_counter() - started, 2),
                "prices": len(prediction.prices),
                "cost_usd": round(prediction.cost_usd, 5),
            }
        )
    except (LLMError, Exception) as exc:  # the demo must report failures, not hang the stream
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:300]
        job.push({"stage": "failed", "message": job.error})
    finally:
        await client.aclose()
        cache.close()


@router.get("/limits", response_model=TryLimits)
def get_limits(request: Request) -> TryLimits:
    return limits(request)


@router.post("/jobs", response_model=TryJob, status_code=202)
async def start(request: Request, file: UploadFile) -> TryJob:
    settings, state = _settings(request), _state(request)
    current = limits(request)
    if not current.enabled:
        raise HTTPException(
            429 if "budget" in (current.reason or "") or "uploads" in (current.reason or "") else 503, current.reason
        )
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "file is larger than 10 MB")
    root: Path = settings.data_root / "try"
    _cleanup(root, state)
    try:
        images = pages_from_upload(file.filename or "upload", data)[:2]
    except UploadError as exc:
        raise HTTPException(422, str(exc)) from exc
    job_id = secrets.token_urlsafe(9)
    folder = root / job_id
    folder.mkdir(parents=True)
    pages = []
    for i, img in enumerate(images):
        img.thumbnail((2400, 2400))
        img.save(folder / f"page-{i}.jpg", format="JPEG", quality=90)
        pages.append(Page(index=i, width=img.width, height=img.height, image=f"page-{i}.jpg"))
    state.by_ip[_client_ip(request)].append(time.time())
    job = Job(job_id=job_id, folder=folder, pages=pages, created_at=datetime.now(UTC))
    state.jobs[job_id] = job
    cfg = RunConfig.load(settings.try_config)
    task = asyncio.create_task(_run(job, cfg, state))
    request.app.state.try_tasks = getattr(request.app.state, "try_tasks", set()) | {task}
    task.add_done_callback(lambda t: request.app.state.try_tasks.discard(t))
    return _view(job, "/api/try/jobs")


def _job(request: Request, job_id: str) -> Job:
    job = _state(request).jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "unknown or expired job")
    return job


@router.get("/jobs/{job_id}", response_model=TryJob)
def get_job(request: Request, job_id: str) -> TryJob:
    return _view(_job(request, job_id), "/api/try/jobs")


@router.get("/jobs/{job_id}/events")
async def events(request: Request, job_id: str) -> EventSourceResponse:
    job = _job(request, job_id)

    async def stream() -> AsyncIterator[dict[str, str]]:
        sent = 0
        while True:
            while sent < len(job.events):
                event = job.events[sent]
                sent += 1
                yield {"event": "stage", "data": json.dumps(event, ensure_ascii=False)}
            if job.status != "running" or await request.is_disconnected():
                return
            job.changed.clear()
            try:
                await asyncio.wait_for(job.changed.wait(), timeout=15)
            except TimeoutError:
                yield {"event": "ping", "data": "{}"}

    return EventSourceResponse(stream())


@router.get("/jobs/{job_id}/pages/{page}", response_class=FileResponse)
def job_page(request: Request, job_id: str, page: int) -> FileResponse:
    job = _job(request, job_id)
    if not 0 <= page < len(job.pages):
        raise HTTPException(404, "unknown page")
    return FileResponse(job.folder / job.pages[page].image)


@router.get("/gallery", response_model=list[GalleryItem])
def gallery() -> list[GalleryItem]:
    items = []
    for path in sorted(GALLERY_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        items.append(GalleryItem.model_validate(raw))
    return items


@router.get("/gallery/{name}", response_class=FileResponse)
def gallery_image(name: str) -> FileResponse:
    path = (GALLERY_DIR / name).resolve()
    if GALLERY_DIR.resolve() not in path.parents or path.suffix not in (".jpg", ".png") or not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path)
