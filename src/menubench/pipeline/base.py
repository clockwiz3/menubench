"""Pipeline contract shared by the CLI runner, the web demo and the annotator's pre-labelling."""

from __future__ import annotations

import inspect
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from PIL import Image

from menubench.llm import LLMClient
from menubench.llm.models import ModelSpec, resolve
from menubench.schema import CatalogEntry, MenuPrediction

Emit = Callable[[str, dict[str, Any]], Awaitable[None] | None]


async def _noop(stage: str, data: dict[str, Any]) -> None:
    return None


@dataclass
class MenuInput:
    menu_id: str
    pages: list[Image.Image]
    catalog: tuple[CatalogEntry, ...] = ()  # track B; ground-truth prices are never passed in


@dataclass
class StageLog:
    """Collects per-stage outputs (the trace) and forwards progress events to the caller."""

    emit: Emit = _noop
    trace: dict[str, Any] = field(default_factory=dict)
    started: float = field(default_factory=time.perf_counter)

    async def stage(self, name: str, **data: Any) -> None:
        self.trace.setdefault("stages", []).append(
            {"stage": name, "t": round(time.perf_counter() - self.started, 3), **data}
        )
        result = self.emit(name, data)
        if inspect.isawaitable(result):
            await result


class Pipeline(ABC):
    name: ClassVar[str]
    roles: ClassVar[tuple[str, ...]]  # model roles this pipeline needs, e.g. ("ocr",)

    def __init__(self, client: LLMClient, models: dict[str, str], params: dict[str, Any] | None = None) -> None:
        missing = [r for r in self.roles if r not in models]
        if missing:
            raise ValueError(f"pipeline {self.name} needs models for: {', '.join(missing)}")
        self.client = client
        self.models: dict[str, ModelSpec] = {role: resolve(model_id) for role, model_id in models.items()}
        self.params = params or {}

    @abstractmethod
    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction: ...

    def estimate_calls(self, pages: int, prices_hint: int) -> list[tuple[str, int]]:
        """(role, number of image calls) for cost estimation; text-only calls are counted as image calls too."""
        return [(role, pages) for role in self.roles]
