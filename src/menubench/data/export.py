"""Builds the public release of the real-menu golden set in the layout the Hugging Face card describes.

photos/<split>/metadata.jsonl + images: the author's own photos, re-encoded without EXIF.
online/<split>.jsonl: menus published on venues' websites, annotations and a source link only; the image is not
redistributed. Venues get opaque ids (v01, v02, ...) that stay stable across releases.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from PIL import Image

from menubench.data.real import RealStore, Status
from menubench.schema import BBox, MenuAnnotation

SPLITS = {"real-dev": "dev", "real-test": "test"}
VENUES_FILE = "venues.json"  # group name -> opaque id; kept next to the private data, never released


class ExportError(RuntimeError):
    pass


@dataclass
class ExportReport:
    rows: dict[str, int] = field(default_factory=dict)  # "photos/dev" -> pages
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (menu_id, reason)


def _box(b: BBox) -> list[float]:
    return [round(b.x0, 5), round(b.y0, 5), round(b.x1, 5), round(b.y1, 5)]


def _amount(v: Decimal | None) -> str | None:
    return None if v is None else format(v.normalize(), "f")


def venue_ids(store: RealStore, groups: list[str]) -> dict[str, str]:
    """Opaque, stable venue ids: known groups keep theirs, new ones get the next number."""
    path = store.root / VENUES_FILE
    known: dict[str, str] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for group in sorted(set(groups) - set(known)):
        known[group] = f"v{len(known) + 1:02d}"
    path.write_text(json.dumps(known, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return known


def page_rows(ann: MenuAnnotation, venue: str) -> list[dict[str, Any]]:
    rows = []
    for page in ann.pages:
        rows.append(
            {
                "menu_id": ann.menu_id,
                "page": page.index,
                "venue_id": venue,
                "width": page.width,
                "height": page.height,
                "lang": ann.lang,
                "tags": list(ann.tags),
                "items": [
                    {"id": it.id, "name": it.name, "bbox": _box(it.bbox)} for it in ann.items if it.page == page.index
                ],
                "prices": [
                    {
                        "id": p.id,
                        "value": _amount(p.value),
                        "value_max": _amount(p.value_max),
                        "currency": p.currency,
                        "kind": p.kind.value,
                        "size_label": p.size_label,
                        "bbox": _box(p.bbox),
                        "item_ids": list(p.item_ids),
                    }
                    for p in ann.prices
                    if p.page == page.index
                ],
            }
        )
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def export_release(store: RealStore, out: Path, card: Path | None = None, draft: bool = False) -> ExportReport:
    """Writes the release into `out`. Without `draft`, refuses until every finished menu has a locked split."""
    finished = [m for m in store.ids() if store.meta(m).status is Status.ANNOTATED and store.meta(m).split in SPLITS]
    if not finished:
        raise ExportError("no finished menus in real-dev or real-test")
    unlocked = [m for m in finished if not store.meta(m).split_locked]
    if unlocked and not draft:
        raise ExportError(
            f"{len(unlocked)} finished menus have no fixed split yet; run `menubench real split` first "
            "(or pass draft=True for a preview that must not be published)"
        )
    groups = {m: store.meta(m).group or f"menu:{m}" for m in finished}
    venues = venue_ids(store, list(groups.values()))

    for sub in ("photos", "online"):
        shutil.rmtree(out / sub, ignore_errors=True)
    report = ExportReport()
    photos: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS.values()}
    online: dict[str, list[dict[str, Any]]] = {s: [] for s in SPLITS.values()}
    for menu_id in finished:
        meta, ann = store.meta(menu_id), store.annotation(menu_id)
        split = SPLITS[meta.split]
        rows = page_rows(ann, venues[groups[menu_id]])
        if meta.source_url:
            for row in rows:
                online[split].append({**row, "source_url": meta.source_url})
            continue
        if "screenshot" in ann.tags:
            report.skipped.append((menu_id, "screenshot without a source link"))
            continue
        folder = out / "photos" / split
        folder.mkdir(parents=True, exist_ok=True)
        for row, page in zip(rows, ann.pages, strict=True):
            name = f"{menu_id}-p{page.index}.jpg"
            with Image.open(store.root / page.image) as img:
                # Re-encoding drops EXIF: no GPS, camera or time stamps leave with the photo.
                img.convert("RGB").save(folder / name, format="JPEG", quality=92)
            photos[split].append({"file_name": name, **row})

    for split in SPLITS.values():
        _write_jsonl(out / "photos" / split / "metadata.jsonl", photos[split])
        _write_jsonl(out / "online" / f"{split}.jsonl", online[split])
        report.rows[f"photos/{split}"] = len(photos[split])
        report.rows[f"online/{split}"] = len(online[split])
    if card is not None and card.exists():
        shutil.copyfile(card, out / "README.md")
    return report
