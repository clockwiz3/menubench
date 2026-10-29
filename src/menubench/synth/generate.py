"""Synthetic dataset generation: content → HTML template → render → ground truth."""

from __future__ import annotations

import io
import json
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined
from PIL import Image

from menubench.schema import (
    AugmentLevel,
    BBox,
    CatalogEntry,
    MenuAnnotation,
    MenuItem,
    Page,
    PriceAnnotation,
    Source,
    TextLine,
    TextRole,
)
from menubench.synth.augment import augment
from menubench.synth.catalog import make_catalog
from menubench.synth.content import ContentOptions, MenuContent, generate_content
from menubench.synth.render import Box, Rendered, Renderer

GENERATOR_VERSION = "2"

FONTS = (
    "Georgia, serif",
    "Arial, sans-serif",
    "'Trebuchet MS', sans-serif",
    "Verdana, sans-serif",
    "'Times New Roman', serif",
    "'Segoe UI', sans-serif",
    "'Palatino Linotype', serif",
    "'Courier New', monospace",
)
PALETTES = (  # bg, fg, accent, muted
    ("#ffffff", "#1d1d1f", "#b3261e", "#8a8a8a"),
    ("#f7f0e1", "#2b2118", "#7a3e12", "#9b8b76"),
    ("#1c1c1c", "#f2f2f2", "#f2b33d", "#9a9a9a"),
    ("#2f3b33", "#eef2ea", "#ffd36b", "#a9b8ac"),
    ("#0f1d33", "#f4f6fb", "#5cc8ff", "#8b9bb8"),
    ("#eef8f3", "#163a2b", "#1d7a52", "#7ea896"),
)


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    theme: Callable[[random.Random], dict[str, Any]]


def _common_theme(rng: random.Random, width: int) -> dict[str, Any]:
    bg, fg, accent, muted = rng.choice(PALETTES)
    font = rng.choice(FONTS)
    return {
        "bg": bg,
        "fg": fg,
        "accent": accent,
        "muted": muted,
        "font": font,
        "title_font": rng.choice((font, *FONTS)),
        "size": rng.randint(15, 22),
        "width": width,
        "padding": rng.randint(30, 60),
        "title_align": rng.choice(("left", "center")),
        "price_weight": rng.choice((400, 700)),
    }


def _classic_theme(rng: random.Random) -> dict[str, Any]:
    width = rng.choice((900, 1100, 1300))
    theme = _common_theme(rng, width)
    theme["columns"] = 2 if width >= 1100 else 1
    theme["leaders"] = rng.random() < 0.7
    return theme


def _cards_theme(rng: random.Random) -> dict[str, Any]:
    width = rng.choice((1000, 1280, 1600))
    theme = _common_theme(rng, width)
    theme["columns"] = {1000: 2, 1280: 3, 1600: 4}[width]
    theme["photos"] = rng.random() < 0.6
    return theme


def _table_theme(rng: random.Random) -> dict[str, Any]:
    theme = _common_theme(rng, rng.choice((900, 1100)))
    theme["zebra"] = rng.random() < 0.5
    return theme


def _chalk_theme(rng: random.Random) -> dict[str, Any]:
    width = rng.choice((900, 1200))
    theme = _common_theme(rng, width)
    theme.update(
        bg=rng.choice(("#2f3b33", "#1f2421", "#262626")),
        fg="#f2f0e6",
        accent=rng.choice(("#ffd36b", "#f6a6a6", "#9fe3c4")),
        muted="#b9b6aa",
        font=rng.choice(("'Segoe Print', cursive", "'Ink Free', cursive", "'Comic Sans MS', cursive")),
        columns=2 if width >= 1200 else 1,
    )
    theme["title_font"] = theme["font"]
    return theme


def _price_left_theme(rng: random.Random) -> dict[str, Any]:
    theme = _common_theme(rng, rng.choice((800, 1000)))
    theme["price_col"] = rng.choice((5, 6, 7))
    return theme


def _tv_theme(rng: random.Random) -> dict[str, Any]:
    theme = _common_theme(rng, 1920)
    bg, fg, accent, muted = rng.choice(PALETTES[2:5])
    theme.update(bg=bg, fg=fg, accent=accent, muted=muted, size=rng.randint(24, 30), columns=rng.choice((3, 4)))
    return theme


def _narrow_theme(rng: random.Random) -> dict[str, Any]:
    theme = _common_theme(rng, rng.choice((560, 640)))
    theme["size"] = rng.randint(15, 18)
    return theme


TEMPLATES: dict[str, TemplateSpec] = {
    "classic_columns": TemplateSpec("classic_columns", _classic_theme),
    "cards_grid": TemplateSpec("cards_grid", _cards_theme),
    "sizes_table": TemplateSpec("sizes_table", _table_theme),
    "chalkboard": TemplateSpec("chalkboard", _chalk_theme),
    "narrow_stand": TemplateSpec("narrow_stand", _narrow_theme),
    "price_left": TemplateSpec("price_left", _price_left_theme),
    "tv_landscape": TemplateSpec("tv_landscape", _tv_theme),
}
# Layouts the pipeline never sees during development: the test split checks transfer to unseen designs.
TEST_ONLY_TEMPLATES = ("price_left", "tv_landscape")

V1_CONTENT: dict[str, Any] = {
    "description_rate": 0.45,
    "long_description_rate": 0.15,
    "weight_rate": 0.25,
    "hard_cases": {"crossed": 0.06, "from": 0.04, "range": 0.03},
}

_ROLES = {role.value: role for role in TextRole}

_env = Environment(
    loader=PackageLoader("menubench.synth", "templates"),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass
class SynthConfig:
    n: int = 300
    seed: int = 42
    langs: tuple[str, ...] = ("ru", "en")
    templates: tuple[str, ...] = tuple(TEMPLATES)
    test_only: tuple[str, ...] = TEST_ONLY_TEMPLATES
    dev_fraction: float = 0.3
    augment: dict[str, float] = field(default_factory=lambda: {"clean": 0.3, "scan": 0.35, "photo": 0.35})
    content: dict[str, Any] = field(default_factory=lambda: dict(V1_CONTENT))  # extra ContentOptions fields
    catalog: bool = True


@dataclass(frozen=True)
class SynthMenu:
    annotation: MenuAnnotation
    png: bytes  # image bytes; PNG for clean renders, JPEG after augmentation
    html: str
    ext: str = "png"


def render_html(content: MenuContent, template: str, theme: dict[str, Any]) -> str:
    return _env.get_template(f"{template}.html.j2").render(menu=content, theme=theme)


def build_menu(
    renderer: Renderer,
    menu_id: str,
    seed: int,
    lang: str,
    template: str,
    augment_level: AugmentLevel = AugmentLevel.CLEAN,
    with_catalog: bool = False,
    **content_opts: Any,
) -> SynthMenu:
    rng = random.Random(seed)
    content, _style = generate_content(rng, ContentOptions(lang=lang, **content_opts))
    theme = TEMPLATES[template].theme(rng)
    html = render_html(content, template, theme)
    rendered = renderer.render(html, width=int(theme["width"]))
    catalog, mapping = make_catalog(content, rng) if with_catalog else ((), {})
    annotation = to_annotation(menu_id, seed, template, content, rendered, catalog, mapping)
    image, ext, annotation = augment(rendered.png, annotation, augment_level, rng)
    return SynthMenu(annotation=annotation, png=image, html=html, ext=ext)


def to_annotation(
    menu_id: str,
    seed: int,
    template: str,
    content: MenuContent,
    rendered: Rendered,
    catalog: tuple[CatalogEntry, ...] = (),
    mapping: dict[str, str | None] | None = None,
) -> MenuAnnotation:
    with Image.open(io.BytesIO(rendered.png)) as img:
        width, height = img.size

    def bbox(box: Box) -> BBox:
        x0, y0 = max(0.0, box.x0 / width), max(0.0, box.y0 / height)
        x1, y1 = min(1.0, box.x1 / width), min(1.0, box.y1 / height)
        return BBox(x0=x0, y0=y0, x1=max(x1, x0 + 1e-6), y1=max(y1, y0 + 1e-6))

    by_id = {(e.kind, e.id): e for e in rendered.elements if e.id}
    items: list[MenuItem] = []
    prices: list[PriceAnnotation] = []
    for section in content.sections:
        for spec in section.items:
            item_el = by_id.get(("item", spec.id))
            if item_el is None:
                raise RuntimeError(f"{menu_id}: item {spec.id} was not rendered")
            items.append(
                MenuItem(
                    id=spec.id,
                    page=0,
                    name=spec.name,
                    bbox=bbox(item_el.box),
                    section=section.title,
                    description=spec.description,
                    catalog_id=(mapping or {}).get(spec.id),
                )
            )
            for price in [*spec.prices, *([spec.old_price] if spec.old_price else [])]:
                price_el = by_id.get(("price", price.id))
                if price_el is None:
                    raise RuntimeError(f"{menu_id}: price {price.id} was not rendered")
                prices.append(
                    PriceAnnotation(
                        id=price.id,
                        page=0,
                        value=price.value,
                        value_max=price.value_max,
                        currency=content.currency,
                        kind=price.kind,
                        size_label=price.size_label,
                        bbox=bbox(price_el.box),
                        item_ids=(spec.id,),
                    )
                )
    lines = tuple(
        TextLine(page=0, text=line.text, bbox=bbox(line.box), role=_ROLES.get(el.kind, TextRole.OTHER))
        for el in rendered.elements
        for line in el.lines
    )
    return MenuAnnotation(
        menu_id=menu_id,
        source=Source.SYNTHETIC,
        lang=content.lang,
        pages=(Page(index=0, width=width, height=height, image=f"{menu_id}/page-0.png"),),
        items=tuple(items),
        prices=tuple(prices),
        catalog=catalog,
        lines=lines,
        template=template,
        seed=seed,
        tags=tuple(sorted(content.tags)),
    )


@dataclass(frozen=True)
class MenuPlan:
    menu_id: str
    seed: int
    lang: str
    template: str
    split: str
    augment: AugmentLevel


def plan_menus(cfg: SynthConfig) -> Iterable[MenuPlan]:
    """Pure function of the config: same config, same dataset."""
    rng = random.Random(cfg.seed)
    shared = [t for t in cfg.templates if t not in cfg.test_only]
    levels = [AugmentLevel(k) for k in cfg.augment]
    weights = list(cfg.augment.values())
    counters = {"dev": 0, "test": 0}
    for i in range(cfg.n):
        menu_seed = rng.randrange(2**31)
        split = "dev" if rng.random() < cfg.dev_fraction else "test"
        pool = shared if split == "dev" else list(cfg.templates)
        template = pool[counters[split] % len(pool)]
        counters[split] += 1
        yield MenuPlan(
            menu_id=f"syn-{cfg.seed}-{i:04d}",
            seed=menu_seed,
            lang=cfg.langs[i % len(cfg.langs)],
            template=template,
            split=split,
            augment=rng.choices(levels, weights)[0],
        )


def generate_dataset(out: Path, cfg: SynthConfig, on_menu: Callable[[str], None] | None = None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    with Renderer() as renderer:
        for plan in plan_menus(cfg):
            menu = build_menu(
                renderer,
                plan.menu_id,
                plan.seed,
                plan.lang,
                plan.template,
                augment_level=plan.augment,
                with_catalog=cfg.catalog,
                **cfg.content,
            )
            menu_dir = out / plan.menu_id
            menu_dir.mkdir(exist_ok=True)
            (menu_dir / f"page-0.{menu.ext}").write_bytes(menu.png)
            (menu_dir / "annotation.json").write_text(menu.annotation.model_dump_json(indent=1), encoding="utf-8")
            index.append(
                {
                    "menu_id": plan.menu_id,
                    "split": plan.split,
                    "lang": plan.lang,
                    "template": plan.template,
                    "augment": plan.augment.value,
                }
            )
            if on_menu:
                on_menu(plan.menu_id)
    meta = {
        "generator_version": GENERATOR_VERSION,
        "seed": cfg.seed,
        "n": cfg.n,
        "templates": cfg.templates,
        "test_only": cfg.test_only,
        "augment": cfg.augment,
    }
    (out / "dataset.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    with (out / "index.jsonl").open("w", encoding="utf-8") as f:
        for row in index:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(index)
