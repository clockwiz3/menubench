"""Model registry: per-model quirks that the pipeline needs to know (box format, image budget)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from menubench.llm.boxes import BoxFormat

DEFAULT_REGISTRY = Path("configs/models.yaml")


class ModelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str | None = None
    box_format: BoxFormat = BoxFormat.AUTO
    max_image_side: int = 1600
    structured_output: bool = False  # send a JSON schema (response_format) instead of trusting the prompt
    fallback: list[str] = []

    @property
    def name(self) -> str:
        return self.label or self.id.split("/")[-1]


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, ModelSpec]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {m["id"]: ModelSpec.model_validate(m) for m in raw.get("models", [])}


def resolve(model_id: str, registry: dict[str, ModelSpec] | None = None) -> ModelSpec:
    registry = load_registry() if registry is None else registry
    return registry.get(model_id) or ModelSpec(id=model_id)
