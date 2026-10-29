import numpy as np
from PIL import Image, ImageDraw, ImageFont

from menubench.detect.refine import refine_box
from menubench.schema import BBox


def _menu_line() -> tuple[np.ndarray, BBox]:
    """A pale weight and a bright price on one line, like '320 г / 290 ₽' on many menus."""
    img = Image.new("RGB", (800, 200), (225, 95, 50))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=48)
    draw.text((40, 70), "320 g /", fill=(240, 170, 140), font=font)
    draw.text((250, 70), "290 R", fill=(255, 255, 255), font=font)
    x0, y0, x1, y1 = draw.textbbox((250, 70), "290 R", font=font)
    w, h = img.size
    return np.asarray(img), BBox(x0=x0 / w, y0=y0 / h, x1=x1 / w, y1=y1 / h)


def test_snaps_a_shifted_box_to_the_price_ink() -> None:
    image, truth = _menu_line()
    shift = 0.03  # the model's box starts inside the first digit and spills to the right
    model = BBox(x0=truth.x0 + shift, y0=truth.y0 - 0.02, x1=min(1, truth.x1 + shift), y1=truth.y1 + 0.03)
    refined = refine_box(image, model, words_expected=2)
    assert refined is not None
    assert refined.iou(truth) > 0.85
    assert refined.x0 > truth.x0 - 0.01  # the pale "320 g /" next to it stays outside


def test_keeps_the_model_box_when_nothing_is_there() -> None:
    blank = np.full((200, 800, 3), (225, 95, 50), dtype=np.uint8)
    assert refine_box(blank, BBox(x0=0.3, y0=0.3, x1=0.5, y1=0.5), 1) is None


def test_grows_a_box_that_covers_only_the_currency() -> None:
    image, truth = _menu_line()
    width = truth.x1 - truth.x0
    model = BBox(x0=truth.x1 - width * 0.25, y0=truth.y0, x1=truth.x1, y1=truth.y1)  # just "R"
    refined = refine_box(image, model, words_expected=2)
    assert refined is not None and refined.iou(truth) > 0.85
