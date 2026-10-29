"""FastAPI application: JSON API under /api, the built Vue app for everything else."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from menubench import __version__
from menubench.llm import load_dotenv
from menubench.runs import RUNS_DIR
from menubench.server import annotate_api, runs_api, try_api

WEB_DIST = Path("web/dist")


@dataclass
class Settings:
    runs_root: Path = RUNS_DIR
    web_dist: Path = WEB_DIST
    data_root: Path = Path("data")
    prelabel_config: Path = Path("configs/second-opinion-claude-cal.yaml")
    try_config: Path = Path("configs/second-opinion-claude-cal.yaml")
    try_daily_budget_usd: float = 1.0
    try_uploads_per_ip: int = 10
    trust_proxy: bool = False  # use X-Forwarded-For for rate limits (only behind a trusted proxy)
    sections: tuple[str, ...] = ("runs", "annotate", "try")

    @classmethod
    def from_env(cls) -> Settings:
        """Deployment knobs; the public demo runs with MENUBENCH_SECTIONS=try,runs."""
        env = os.environ
        return cls(
            runs_root=Path(env.get("MENUBENCH_RUNS", str(RUNS_DIR))),
            data_root=Path(env.get("MENUBENCH_DATA", "data")),
            web_dist=Path(env.get("MENUBENCH_WEB_DIST", str(WEB_DIST))),
            try_config=Path(env.get("MENUBENCH_TRY_CONFIG", "configs/second-opinion-claude-cal.yaml")),
            try_daily_budget_usd=float(env.get("MENUBENCH_TRY_BUDGET_USD", "1.0")),
            try_uploads_per_ip=int(env.get("MENUBENCH_TRY_UPLOADS_PER_IP", "10")),
            trust_proxy=env.get("MENUBENCH_TRUST_PROXY", "") == "1",
            sections=tuple(
                s.strip() for s in env.get("MENUBENCH_SECTIONS", "runs,annotate,try").split(",") if s.strip()
            ),
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    load_dotenv()  # the demo checks for the API key before any model client exists
    settings = settings or Settings.from_env()
    app = FastAPI(title="MenuBench", version=__version__)
    app.state.settings = settings
    # The annotation tool writes to disk and spends money on pre-labelling: it is off in the public deployment.
    routers = {"runs": runs_api.router, "annotate": annotate_api.router, "try": try_api.router}
    for name in settings.sections:
        app.include_router(routers[name])

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, object]:
        return {"status": "ok", "version": __version__, "sections": list(settings.sections)}

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
