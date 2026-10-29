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
    BBox,
    MenuAnnotation,
    MenuItem,
    Page,
    PriceAnnotation,
    Source,
    TextLine,
    TextRole,
)
from menubench.synth.content import ContentOptions, MenuContent, generate_content
from menubench.synth.render import Box, Rendered, Renderer

GENERATOR_VERSION = "1"

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


TEMPLATES: dict[str, TemplateSpec] = {
    "classic_columns": TemplateSpec("classic_columns", _classic_theme),
    "cards_grid": TemplateSpec("cards_grid", _cards_theme),
    "sizes_table": TemplateSpec("sizes_table", _table_theme),
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
    n: int = 50
    seed: int = 42
    langs: tuple[str, ...] = ("ru", "en")
    templates: tuple[str, ...] = tuple(TEMPLATES)
    dev_fraction: float = 0.3
    content: dict[str, Any] = field(default_factory=dict)  # extra ContentOptions fields


@dataclass(frozen=True)
class SynthMenu:
    annotation: MenuAnnotation
    png: bytes
    html: str


def render_html(content: MenuContent, template: str, theme: dict[str, Any]) -> str:
    return _env.get_template(f"{template}.html.j2").render(menu=content, theme=theme)


def build_menu(renderer: Renderer, menu_id: str, seed: int, lang: str, template: str, **content_opts: Any) -> SynthMenu:
    rng = random.Random(seed)
    content, _style = generate_content(rng, ContentOptions(lang=lang, **content_opts))
    theme = TEMPLATES[template].theme(rng)
    html = render_html(content, template, theme)
    rendered = renderer.render(html, width=int(theme["width"]))
    annotation = to_annotation(menu_id, seed, template, content, rendered)
    return SynthMenu(annotation=annotation, png=rendered.png, html=html)


def to_annotation(menu_id: str, seed: int, template: str, content: MenuContent, rendered: Rendered) -> MenuAnnotation:
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
                )
            )
            for price in spec.prices:
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
        lines=lines,
        template=template,
        seed=seed,
        tags=tuple(sorted(content.tags)),
    )


def plan_menus(cfg: SynthConfig) -> Iterable[tuple[str, int, str, str, str]]:
    """Yields (menu_id, seed, lang, template, split). Pure function of the config."""
    rng = random.Random(cfg.seed)
    for i in range(cfg.n):
        menu_seed = rng.randrange(2**31)
        lang = cfg.langs[i % len(cfg.langs)]
        template = cfg.templates[(i // len(cfg.langs)) % len(cfg.templates)]
        split = "dev" if rng.random() < cfg.dev_fraction else "test"
        yield f"syn-{cfg.seed}-{i:04d}", menu_seed, lang, template, split


def generate_dataset(out: Path, cfg: SynthConfig, on_menu: Callable[[str], None] | None = None) -> int:
    out.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    with Renderer() as renderer:
        for menu_id, seed, lang, template, split in plan_menus(cfg):
            menu = build_menu(renderer, menu_id, seed, lang, template, **cfg.content)
            menu_dir = out / menu_id
            menu_dir.mkdir(exist_ok=True)
            (menu_dir / "page-0.png").write_bytes(menu.png)
            (menu_dir / "annotation.json").write_text(menu.annotation.model_dump_json(indent=1), encoding="utf-8")
            index.append({"menu_id": menu_id, "split": split, "lang": lang, "template": template})
            if on_menu:
                on_menu(menu_id)
    meta = {"generator_version": GENERATOR_VERSION, "seed": cfg.seed, "n": cfg.n, "templates": cfg.templates}
    (out / "dataset.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    with (out / "index.jsonl").open("w", encoding="utf-8") as f:
        for row in index:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(index)
