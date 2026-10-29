"""HTML → PNG with exact text geometry, using a headless Chromium."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

from playwright.sync_api import Browser, Playwright, sync_playwright

# Collects every [data-mb-kind] element. Geometry comes from per-word ranges, so wrapped text yields
# one entry per visual line and boxes hug the glyphs instead of the layout box.
_COLLECT_JS = """
() => {
  const words = (el) => {
    const out = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const re = /\\S+/g;
      let m;
      while ((m = re.exec(node.data))) {
        const r = document.createRange();
        r.setStart(node, m.index);
        r.setEnd(node, m.index + m[0].length);
        const b = r.getBoundingClientRect();
        if (b.width > 0 && b.height > 0) {
          out.push({ t: m[0], x0: b.left, y0: b.top, x1: b.right, y1: b.bottom });
        }
      }
    }
    return out;
  };
  const group = (ws) => {
    const lines = [];
    for (const w of ws) {
      const cy = (w.y0 + w.y1) / 2;
      const line = lines.find((l) => Math.abs(l.cy - cy) < (w.y1 - w.y0) * 0.5);
      if (line) { line.words.push(w); } else { lines.push({ cy, words: [w] }); }
    }
    return lines.map((l) => {
      l.words.sort((a, b) => a.x0 - b.x0);
      return {
        text: l.words.map((w) => w.t).join(' '),
        x0: Math.min(...l.words.map((w) => w.x0)), y0: Math.min(...l.words.map((w) => w.y0)),
        x1: Math.max(...l.words.map((w) => w.x1)), y1: Math.max(...l.words.map((w) => w.y1)),
      };
    }).sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0);
  };
  const doc = document.documentElement;
  const elements = [...document.querySelectorAll('[data-mb-kind]')].map((el) => {
    const lines = group(words(el));
    return { kind: el.dataset.mbKind, id: el.dataset.mbId || null, lines };
  }).filter((e) => e.lines.length > 0);
  return { width: doc.scrollWidth, height: doc.scrollHeight, elements };
}
"""


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class RenderedLine:
    text: str
    box: Box


@dataclass(frozen=True)
class RenderedElement:
    kind: str
    id: str | None
    lines: tuple[RenderedLine, ...]

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines)

    @property
    def box(self) -> Box:
        return Box(
            min(line.box.x0 for line in self.lines),
            min(line.box.y0 for line in self.lines),
            max(line.box.x1 for line in self.lines),
            max(line.box.y1 for line in self.lines),
        )


@dataclass(frozen=True)
class Rendered:
    png: bytes
    width: int
    height: int
    elements: tuple[RenderedElement, ...]


def _line(raw: dict[str, Any]) -> RenderedLine:
    return RenderedLine(str(raw["text"]), Box(raw["x0"], raw["y0"], raw["x1"], raw["y1"]))


class Renderer:
    """Keeps one browser alive across many menus; use as a context manager."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None

    def __enter__(self) -> Self:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def render(self, html: str, width: int) -> Rendered:
        assert self._browser, "Renderer must be used as a context manager"
        page = self._browser.new_page(viewport={"width": width, "height": 800}, device_scale_factor=1)
        try:
            page.set_content(html, wait_until="load")
            page.evaluate("document.fonts.ready")
            data = page.evaluate(_COLLECT_JS)
            png = page.screenshot(full_page=True, type="png")
        finally:
            page.close()
        elements = tuple(
            RenderedElement(e["kind"], e["id"], tuple(_line(raw) for raw in e["lines"]))
            for e in data["elements"]
        )
        return Rendered(png=png, width=int(data["width"]), height=int(data["height"]), elements=elements)
