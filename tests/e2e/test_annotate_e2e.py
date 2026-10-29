"""Browser test of the annotation editor: draw an item and its price, finish, check the saved ground truth.

Needs the built frontend (cd web && npm run build) and a Playwright Chromium; run with `pytest -m e2e`.
"""

import io
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from PIL import Image, ImageDraw

from menubench.data.real import RealStore
from menubench.server.app import Settings, create_app

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not (WEB_DIST / "index.html").exists(), reason="frontend is not built"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[str, RealStore]]:
    app = create_app(Settings(runs_root=tmp_path / "runs", web_dist=WEB_DIST, data_root=tmp_path))
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", RealStore(tmp_path / "real")
    srv.should_exit = True
    thread.join(timeout=5)


def _menu_photo() -> bytes:
    img = Image.new("RGB", (800, 600), "white")
    draw = ImageDraw.Draw(img)
    draw.text((60, 100), "Borscht", fill="black")
    draw.text((600, 100), "350", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_draw_link_and_finish(server: tuple[str, RealStore]) -> None:
    from playwright.sync_api import sync_playwright

    base, store = server
    menu_id = store.create([("menu.jpg", _menu_photo())], lang="en")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(f"{base}/annotate/{menu_id}")
        canvas = page.locator("canvas").first
        canvas.wait_for()
        box = canvas.bounding_box()
        assert box is not None

        def drag(x0: float, y0: float, x1: float, y1: float) -> None:
            page.mouse.move(box["x"] + box["width"] * x0, box["y"] + box["height"] * y0)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * x1, box["y"] + box["height"] * y1, steps=5)
            page.mouse.up()

        page.get_by_role("button", name="Draw item").click()
        drag(0.07, 0.15, 0.25, 0.2)
        page.get_by_label("Name, exactly as printed").fill("Borscht")

        page.get_by_role("button", name="Draw price").click()
        drag(0.74, 0.15, 0.82, 0.2)  # the item is still selected, so the price links to it
        page.get_by_label("Value").fill("350")

        with page.expect_response(lambda r: r.request.method == "PUT" and r.ok):
            page.get_by_role("button", name="Finish").click()
        browser.close()

    ann = store.annotation(menu_id)
    assert [i.name for i in ann.items] == ["Borscht"]
    assert [(str(p.value), p.item_ids) for p in ann.prices] == [("350", (ann.items[0].id,))]
    assert 0.7 < ann.prices[0].bbox.x0 < 0.76
    assert store.meta(menu_id).status == "annotated"
