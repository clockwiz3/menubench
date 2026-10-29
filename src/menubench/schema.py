"""Data model shared by the generator, the pipeline and the evaluator.

Coordinates are normalized to the page (0..1, origin top-left), so annotations survive
resizing and are comparable across models that report boxes in different units.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BBox(_Model):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("bbox must satisfy x0 < x1 and y0 < y1")
        return self

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def iou(self, other: BBox) -> float:
        ix = max(0.0, min(self.x1, other.x1) - max(self.x0, other.x0))
        iy = max(0.0, min(self.y1, other.y1) - max(self.y0, other.y0))
        inter = ix * iy
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


class PriceKind(StrEnum):
    SINGLE = "single"
    SIZE_VARIANT = "size_variant"  # one of several sizes: S/M/L, 0.3/0.5 l
    RANGE = "range"  # 300-450
    FROM = "from"  # "from 300"
    CROSSED = "crossed"  # old price, struck through; must not be shown as current


class Source(StrEnum):
    SYNTHETIC = "synthetic"
    REAL = "real"


class AugmentLevel(StrEnum):
    CLEAN = "clean"
    SCAN = "scan"
    PHOTO = "photo"


class Page(_Model):
    index: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    image: str  # path relative to the dataset root


class TextRole(StrEnum):
    TITLE = "title"
    SECTION = "section"
    ITEM = "item"
    DESCRIPTION = "description"
    PRICE = "price"
    SIZE = "size"  # size label such as "S" or "0.3 l", not a price
    OTHER = "other"  # address, phone, notes: distractors for the price detector


class TextLine(_Model):
    """One visual line of text. Synthetic menus know every line exactly; used to score OCR."""

    page: int = Field(ge=0)
    text: str
    bbox: BBox
    role: TextRole = TextRole.OTHER


class CatalogEntry(_Model):
    id: str
    name: str


class MenuItem(_Model):
    id: str
    page: int = Field(ge=0)
    name: str
    bbox: BBox
    section: str | None = None
    description: str | None = None
    catalog_id: str | None = None  # None: item is absent from the catalog, the right answer is abstain


class PriceAnnotation(_Model):
    id: str
    page: int = Field(ge=0)
    value: Decimal = Field(ge=0)
    value_max: Decimal | None = None  # upper bound for RANGE
    currency: str | None = None  # ISO 4217, None when the menu prints no currency
    kind: PriceKind = PriceKind.SINGLE
    size_label: str | None = None
    bbox: BBox
    item_ids: tuple[str, ...] = ()  # usually one; several when one price covers a group

    @model_validator(mode="after")
    def _range(self) -> Self:
        if (self.kind is PriceKind.RANGE) != (self.value_max is not None):
            raise ValueError("value_max is required for RANGE prices and only for them")
        if self.value_max is not None and self.value_max < self.value:
            raise ValueError("value_max must not be less than value")
        return self


class MenuAnnotation(_Model):
    """Ground truth for one menu."""

    menu_id: str
    source: Source
    lang: str  # BCP 47, e.g. "ru", "en"
    pages: tuple[Page, ...] = Field(min_length=1)
    items: tuple[MenuItem, ...] = ()
    prices: tuple[PriceAnnotation, ...] = ()
    catalog: tuple[CatalogEntry, ...] = ()
    lines: tuple[TextLine, ...] = ()
    template: str | None = None
    augment: AugmentLevel | None = None
    seed: int | None = None
    tags: tuple[str, ...] = ()  # hard-case markers used for report slicing

    @model_validator(mode="after")
    def _references(self) -> Self:
        page_ids = {p.index for p in self.pages}
        item_ids = {i.id for i in self.items}
        catalog_ids = {c.id for c in self.catalog}
        for item in self.items:
            if item.page not in page_ids:
                raise ValueError(f"item {item.id} points to missing page {item.page}")
            if item.catalog_id is not None and item.catalog_id not in catalog_ids:
                raise ValueError(f"item {item.id} points to missing catalog entry {item.catalog_id}")
        for price in self.prices:
            if price.page not in page_ids:
                raise ValueError(f"price {price.id} points to missing page {price.page}")
            missing = set(price.item_ids) - item_ids
            if missing:
                raise ValueError(f"price {price.id} points to missing items {sorted(missing)}")
        return self


class PricePrediction(_Model):
    page: int = Field(ge=0)
    value: Decimal = Field(ge=0)
    value_max: Decimal | None = None
    currency: str | None = None
    kind: PriceKind = PriceKind.SINGLE
    bbox: BBox | None = None
    name: str | None = None
    confidence: float = Field(ge=0, le=1)


class LinkCandidate(_Model):
    catalog_id: str
    score: float = Field(ge=0, le=1)


class LinkDecision(_Model):
    """Track B outcome for one predicted price."""

    action: Literal["link", "hint", "abstain"]
    catalog_id: str | None = None
    candidates: tuple[LinkCandidate, ...] = ()
    reason: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if (self.action == "link") != (self.catalog_id is not None):
            raise ValueError("catalog_id is set for link decisions and only for them")
        if self.action == "hint" and not self.candidates:
            raise ValueError("hint decisions need at least one candidate")
        return self


class MenuPrediction(_Model):
    menu_id: str
    config: str
    prices: tuple[PricePrediction, ...] = ()
    links: tuple[LinkDecision | None, ...] = ()  # aligned with prices; empty when track B is off
    cost_usd: float = Field(default=0.0, ge=0)
    latency_s: float = Field(default=0.0, ge=0)
    error: str | None = None  # set when the pipeline failed on this menu

    @model_validator(mode="after")
    def _aligned(self) -> Self:
        if self.links and len(self.links) != len(self.prices):
            raise ValueError("links must be empty or aligned with prices")
        return self
