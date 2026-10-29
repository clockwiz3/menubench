"""Run directories: one folder per pipeline run, consumed by `eval`, `report` and the web app.

runs/<run_id>/
  run.json             RunInfo
  predictions.jsonl    one MenuPrediction per line
  traces/<menu>.json   per-stage outputs for debugging (optional)
  metrics.json         written by `menubench eval`
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from menubench.schema import MenuPrediction

RUNS_DIR = Path("runs")


class RunInfo(BaseModel):
    run_id: str
    config_name: str
    config: dict[str, Any] = Field(default_factory=dict)
    dataset: str
    split: str
    started_at: datetime
    finished_at: datetime | None = None
    git_sha: str | None = None
    menus: int = 0
    cost_usd: float = 0.0
    errors: int = 0


def git_sha() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def new_run_id(config_name: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{config_name}"


@dataclass(frozen=True)
class RunDir:
    path: Path

    @property
    def run_id(self) -> str:
        return self.path.name

    def info(self) -> RunInfo:
        return RunInfo.model_validate_json((self.path / "run.json").read_text(encoding="utf-8"))

    def write_info(self, info: RunInfo) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / "run.json").write_text(info.model_dump_json(indent=1), encoding="utf-8")

    def predictions(self) -> Iterator[MenuPrediction]:
        path = self.path / "predictions.jsonl"
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield MenuPrediction.model_validate_json(line)

    def append_prediction(self, prediction: MenuPrediction) -> None:
        with (self.path / "predictions.jsonl").open("a", encoding="utf-8") as f:
            f.write(prediction.model_dump_json() + "\n")

    def write_trace(self, menu_id: str, trace: dict[str, Any]) -> None:
        traces = self.path / "traces"
        traces.mkdir(parents=True, exist_ok=True)
        (traces / f"{menu_id}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=1, default=str), "utf-8")

    def trace(self, menu_id: str) -> dict[str, Any] | None:
        path = self.path / "traces" / f"{menu_id}.json"
        if not path.exists():
            return None
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def metrics(self) -> dict[str, Any] | None:
        path = self.path / "metrics.json"
        if not path.exists():
            return None
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data

    def write_metrics(self, metrics: dict[str, Any]) -> None:
        (self.path / "metrics.json").write_text(json.dumps(metrics, indent=1, ensure_ascii=False), "utf-8")


def list_runs(root: Path = RUNS_DIR) -> list[RunDir]:
    if not root.exists():
        return []
    return sorted((RunDir(p) for p in root.iterdir() if (p / "run.json").exists()), key=lambda r: r.run_id)
