"""Annotation tool API: upload real menu photos, pre-label them with the pipeline, save corrected ground truth."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ValidationError

from menubench.data.real import RealStore, Status, UploadError
from menubench.llm import LLMClient, LLMError, ResponseCache
from menubench.pipeline.base import MenuInput, StageLog
from menubench.pipeline.prelabel import prediction_to_draft
from menubench.pipeline.runner import RunConfig, build_pipeline, load_pages_from
from menubench.schema import CatalogEntry, MenuAnnotation, MenuItem, PriceAnnotation

router = APIRouter(prefix="/api/annotate", tags=["annotate"])
MAX_UPLOAD = 15 * 1024 * 1024


class MenuListRow(BaseModel):
    menu_id: str
    status: Status
    split: str
    group: str | None = None
    pages: int
    prices: int
    items: int
    updated_at: datetime


class MenuDraft(BaseModel):
    """What the editor sends back: everything a person can change."""

    lang: str
    items: list[MenuItem]
    prices: list[PriceAnnotation]
    catalog: list[CatalogEntry] = []
    tags: list[str] = []  # slices for reporting: chalkboard, glare, angled, bilingual...
    status: Status
    split: str = "real-test"
    notes: str = ""


class MenuForEditor(BaseModel):
    annotation: MenuAnnotation
    status: Status
    split: str
    split_locked: bool = False
    group: str | None = None
    notes: str
    prelabel_config: str | None


def _store(request: Request) -> RealStore:
    root: Path = request.app.state.settings.data_root / "real"
    return RealStore(root)


def _editor_view(store: RealStore, menu_id: str) -> MenuForEditor:
    meta = store.meta(menu_id)
    return MenuForEditor(
        annotation=store.annotation(menu_id),
        status=meta.status,
        split=meta.split,
        split_locked=meta.split_locked or meta.split == "recheck",
        group=meta.group,
        notes=meta.notes,
        prelabel_config=meta.prelabel_config,
    )


@router.get("/menus", response_model=list[MenuListRow])
def list_menus(request: Request) -> list[MenuListRow]:
    store = _store(request)
    rows = []
    for menu_id in reversed(store.ids()):
        meta, ann = store.meta(menu_id), store.annotation(menu_id)
        rows.append(
            MenuListRow(
                menu_id=menu_id,
                status=meta.status,
                split=meta.split,
                group=meta.group,
                pages=len(ann.pages),
                prices=len(ann.prices),
                items=len(ann.items),
                updated_at=meta.updated_at,
            )
        )
    return rows


@router.post("/menus", response_model=MenuForEditor, status_code=201)
async def upload(request: Request, files: list[UploadFile], lang: str = "ru") -> MenuForEditor:
    payload = []
    total = 0
    for f in files:
        data = await f.read()
        total += len(data)
        if total > MAX_UPLOAD:
            raise HTTPException(413, "upload is larger than 15 MB")
        payload.append((f.filename or "upload", data))
    store = _store(request)
    try:
        menu_id = store.create(payload, lang=lang)
    except UploadError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _editor_view(store, menu_id)


@router.get("/menus/{menu_id}", response_model=MenuForEditor)
def get_menu(request: Request, menu_id: str) -> MenuForEditor:
    try:
        return _editor_view(_store(request), menu_id)
    except KeyError:
        raise HTTPException(404, "unknown menu") from None


@router.put("/menus/{menu_id}", response_model=MenuForEditor)
def save_menu(request: Request, menu_id: str, draft: MenuDraft) -> MenuForEditor:
    store = _store(request)
    try:
        base = store.annotation(menu_id)
    except KeyError:
        raise HTTPException(404, "unknown menu") from None
    if draft.status in (Status.ANNOTATED, Status.REVIEWED):
        unlinked = [p.id for p in draft.prices if not p.item_ids]
        if unlinked:
            raise HTTPException(422, f"link every price to an item before finishing: {', '.join(unlinked)}")
    try:
        annotation = MenuAnnotation(
            menu_id=menu_id,
            source=base.source,
            lang=draft.lang,
            pages=base.pages,
            items=tuple(draft.items),
            prices=tuple(draft.prices),
            catalog=tuple(draft.catalog),
            tags=tuple(sorted({t.strip().lower() for t in draft.tags if t.strip()})),
        )
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'menu'}: {e['msg']}" for e in exc.errors())
        raise HTTPException(422, problems) from exc
    meta = store.meta(menu_id)
    split = meta.split if meta.split_locked or meta.split == "recheck" else draft.split
    store.save(annotation, status=draft.status, split=split, notes=draft.notes)
    return _editor_view(store, menu_id)


async def prelabel_menu(store: RealStore, menu_id: str, config_path: Path) -> None:
    """Runs the pipeline on one menu and stores its proposal as the draft (status: pre-labelled)."""
    base = store.annotation(menu_id)
    cfg = RunConfig.load(config_path)
    cache = ResponseCache()
    client = LLMClient(cache=cache, concurrency=cfg.llm_concurrency)
    try:
        pipeline = build_pipeline(cfg, client)
        prediction = await pipeline.process(MenuInput(menu_id, load_pages_from(store.root, base)), StageLog())
    finally:
        await client.aclose()
        cache.close()
    store.save(prediction_to_draft(base, prediction), status=Status.PRELABELED, prelabel_config=str(config_path))


@router.post("/menus/{menu_id}/prelabel", response_model=MenuForEditor)
async def prelabel(request: Request, menu_id: str) -> MenuForEditor:
    """Runs the reference pipeline and replaces the draft with its proposal. Costs a few tenths of a cent."""
    store = _store(request)
    try:
        store.annotation(menu_id)
    except KeyError:
        raise HTTPException(404, "unknown menu") from None
    config_path: Path = request.app.state.settings.prelabel_config
    try:
        await prelabel_menu(store, menu_id, config_path)
    except LLMError as exc:
        raise HTTPException(503, f"model call failed: {exc}") from exc
    return _editor_view(store, menu_id)


@router.get("/menus/{menu_id}/pages/{page}", response_class=FileResponse)
def page_image(request: Request, menu_id: str, page: int) -> FileResponse:
    try:
        return FileResponse(_store(request).page_path(menu_id, page))
    except KeyError:
        raise HTTPException(404, "unknown page") from None
