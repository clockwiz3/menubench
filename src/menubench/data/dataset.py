"""A dataset is a directory with `index.jsonl` and one folder per menu holding pages and `annotation.json`."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from menubench.schema import MenuAnnotation


@dataclass(frozen=True)
class IndexRow:
    menu_id: str
    split: str
    lang: str | None = None
    template: str | None = None


@dataclass(frozen=True)
class Dataset:
    root: Path

    @cached_property
    def index(self) -> tuple[IndexRow, ...]:
        path = self.root / "index.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; generate it with `menubench synth`")
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                raw = json.loads(line)
                rows.append(IndexRow(raw["menu_id"], raw["split"], raw.get("lang"), raw.get("template")))
        return tuple(rows)

    def ids(self, split: str | None = None, limit: int | None = None) -> list[str]:
        ids = [r.menu_id for r in self.index if split in (None, "all") or r.split == split]
        return ids[:limit] if limit is not None else ids

    def annotation(self, menu_id: str) -> MenuAnnotation:
        path = self.root / menu_id / "annotation.json"
        return MenuAnnotation.model_validate_json(path.read_text(encoding="utf-8"))

    def page_path(self, annotation: MenuAnnotation, page: int = 0) -> Path:
        return self.root / annotation.pages[page].image

    def iter(self, split: str | None = None, limit: int | None = None) -> Iterator[MenuAnnotation]:
        for menu_id in self.ids(split, limit):
            yield self.annotation(menu_id)
