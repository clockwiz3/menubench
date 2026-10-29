"""FastAPI application: JSON API under /api, the built Vue app for everything else."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from menubench import __version__
from menubench.runs import RUNS_DIR
from menubench.server import annotate_api, runs_api

WEB_DIST = Path("web/dist")


@dataclass
class Settings:
    runs_root: Path = RUNS_DIR
    web_dist: Path = WEB_DIST
    data_root: Path = Path("data")
    prelabel_config: Path = Path("configs/full-gemini25-flash-lite-cal.yaml")
    extra: dict[str, object] = field(default_factory=dict)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="MenuBench", version=__version__)
    app.state.settings = settings
    app.include_router(runs_api.router)
    app.include_router(annotate_api.router)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    index = settings.web_dist / "index.html"
    if index.exists():
        app.mount("/assets", StaticFiles(directory=settings.web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path.startswith("api/"):
                raise HTTPException(404, "not found")
            # Client-side routes all resolve to the SPA; real files in dist (favicon etc.) are served as-is.
            candidate = (settings.web_dist / path).resolve()
            if path and candidate.is_file() and settings.web_dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(index)

    return app
