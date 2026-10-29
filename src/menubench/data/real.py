"""Store for real menu photos: upload, drafts, annotation status, and the index used for evaluation.

data/real/<menu_id>/page-<n>.jpg, annotation.json, meta.json; data/real/index.jsonl lists only menus whose
annotation is finished, so evaluation never sees a half-labelled menu.
"""

from __future__ import annotations

import io
import json
import secrets
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from menubench.schema import MenuAnnotation, Page, Source

MAX_SIDE = 3000
FINISHED = ("annotated", "reviewed")


class Status(StrEnum):
    NEW = "new"  # uploaded, nothing labelled yet
    PRELABELED = "prelabeled"  # the pipeline proposed boxes; a person has not checked them
    ANNOTATED = "annotated"  # a person labelled every price
    REVIEWED = "reviewed"  # checked a second time (the agreement subset)


class MenuMeta(BaseModel):
    menu_id: str
    status: Status = Status.NEW
    split: str = "real-test"
    source_files: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    prelabel_config: str | None = None
    notes: str = ""


class UploadError(ValueError):
    pass


def pages_from_upload(name: str, data: bytes) -> list[Image.Image]:
    if name.lower().endswith(".pdf") or data[:4] == b"%PDF":
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        try:
            return [pdf[i].render(scale=2.0).to_pil().convert("RGB") for i in range(min(len(pdf), 8))]
        finally:
            pdf.close()
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:
        raise UploadError(f"{name}: not an image or PDF") from exc
    return [ImageOps.exif_transpose(img).convert("RGB")]


class RealStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, menu_id: str) -> Path:
        path = (self.root / menu_id).resolve()
        if self.root.resolve() not in path.parents or not (path / "meta.json").exists():
            raise KeyError(menu_id)
        return path

    def ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "meta.json").exists())

    def meta(self, menu_id: str) -> MenuMeta:
        return MenuMeta.model_validate_json((self._dir(menu_id) / "meta.json").read_text(encoding="utf-8"))

    def annotation(self, menu_id: str) -> MenuAnnotation:
        return MenuAnnotation.model_validate_json((self._dir(menu_id) / "annotation.json").read_text(encoding="utf-8"))

    def page_path(self, menu_id: str, page: int) -> Path:
        ann = self.annotation(menu_id)
        if not 0 <= page < len(ann.pages):
            raise KeyError(page)
        return self.root / ann.pages[page].image

    def create(self, files: list[tuple[str, bytes]], lang: str = "ru") -> str:
        images = [img for name, data in files for img in pages_from_upload(name, data)]
        if not images:
            raise UploadError("no pages in the upload")
        menu_id = f"real-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(3)}"
        folder = self.root / menu_id
        folder.mkdir(parents=True)
        pages = []
        for i, img in enumerate(images):
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            img.save(folder / f"page-{i}.jpg", format="JPEG", quality=92)
            pages.append(Page(index=i, width=img.width, height=img.height, image=f"{menu_id}/page-{i}.jpg"))
        now = datetime.now(UTC)
        self._write(folder, MenuAnnotation(menu_id=menu_id, source=Source.REAL, lang=lang, pages=tuple(pages)))
        meta = MenuMeta(menu_id=menu_id, source_files=[n for n, _ in files], created_at=now, updated_at=now)
        (folder / "meta.json").write_text(meta.model_dump_json(indent=1), encoding="utf-8")
        return menu_id

    def save(
        self, annotation: MenuAnnotation, status: Status | None = None, split: str | None = None, **meta_updates: object
    ) -> MenuMeta:
        folder = self._dir(annotation.menu_id)
        current = self.annotation(annotation.menu_id)
        if annotation.pages != current.pages:
            raise ValueError("pages cannot be changed after upload")
        self._write(folder, annotation)
        meta = self.meta(annotation.menu_id)
        updates: dict[str, object] = {"updated_at": datetime.now(UTC), **meta_updates}
        if status is not None:
            updates["status"] = status
        if split is not None:
            updates["split"] = split
        meta = meta.model_copy(update=updates)
        (folder / "meta.json").write_text(meta.model_dump_json(indent=1), encoding="utf-8")
        self.rebuild_index()
        return meta

    @staticmethod
    def _write(folder: Path, annotation: MenuAnnotation) -> None:
        (folder / "annotation.json").write_text(annotation.model_dump_json(indent=1), encoding="utf-8")

    def rebuild_index(self) -> None:
        rows = []
        for menu_id in self.ids():
            meta = self.meta(menu_id)
            if meta.status.value in FINISHED:
                rows.append({"menu_id": menu_id, "split": meta.split, "lang": self.annotation(menu_id).lang})
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "index.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
