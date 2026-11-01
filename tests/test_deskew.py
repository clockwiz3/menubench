import asyncio
from decimal import Decimal

from PIL import Image, ImageDraw

from menubench.detect.deskew import Straightened, estimate_skew, straighten
from menubench.pipeline.base import MenuInput, Pipeline, StageLog
from menubench.pipeline.deskewed import Deskewed
from menubench.schema import BBox, MenuPrediction, PricePrediction


def _page(tilt: float) -> Image.Image:
    """A menu-like page: rows of dark dashes standing in for text, tilted by `tilt` degrees counter-clockwise."""
    img = Image.new("RGB", (800, 1000), (245, 240, 225))
    draw = ImageDraw.Draw(img)
    for row in range(18):
        y = 80 + row * 48
        for x in range(60, 700, 26):
            draw.rectangle([x, y, x + 18, y + 14], fill=(30, 30, 30))
    return img.rotate(tilt, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(245, 240, 225))


def test_estimates_the_turn_that_levels_the_rows() -> None:
    angle, gain = estimate_skew(_page(3.5))
    assert abs(angle + 3.5) <= 0.3 and gain > 1.5


def test_level_page_is_left_alone() -> None:
    page = _page(0.0)
    same, turn = straighten(page)
    assert turn is None and same is page


def test_boxes_round_trip() -> None:
    turn = Straightened(angle=4.0, src=(800, 1000), dst=(868, 1053))
    box = BBox(x0=0.5, y0=0.4, x1=0.6, y1=0.42)
    back = turn.to_original(turn.to_straight(box))
    # The hull of a rotated hull grows a little; the centre stays put.
    assert abs((back.x0 + back.x1) / 2 - 0.55) < 1e-3 and abs((back.y0 + back.y1) / 2 - 0.41) < 1e-3
    assert back.x0 <= box.x0 and back.x1 >= box.x1


class _Echo(Pipeline):
    """Reports the box it was told to, on whatever page it is given, and remembers the page size it saw."""

    name = "echo"
    roles = ()

    def __init__(self) -> None:
        super().__init__(client=None, models={})  # type: ignore[arg-type]
        self.seen: tuple[int, int] | None = None

    async def process(self, menu: MenuInput, log: StageLog) -> MenuPrediction:
        self.seen = menu.pages[0].size
        box = BBox(x0=0.45, y0=0.45, x1=0.55, y1=0.47)
        return MenuPrediction(
            menu_id=menu.menu_id,
            config="echo",
            prices=(PricePrediction(page=0, value=Decimal(1), bbox=box, confidence=1.0),),
        )


def test_deskewed_pipeline_reads_the_straight_page_and_maps_back() -> None:
    inner = _Echo()
    page = _page(3.5)
    prediction = asyncio.run(Deskewed(inner).process(MenuInput("m", [page]), StageLog()))
    assert inner.seen is not None and inner.seen != page.size  # the inner pipeline got the turned page
    box = prediction.prices[0].bbox
    assert box is not None and abs((box.x0 + box.x1) / 2 - 0.5) < 0.02  # the centre stays near the middle
