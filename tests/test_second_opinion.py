from decimal import Decimal

from menubench.pipeline.second_opinion import opinion_signals
from menubench.schema import BBox, PricePrediction


def _p(value: int, name: str | None, y: float = 0.1, conf: float = 0.9) -> PricePrediction:
    return PricePrediction(
        page=0, value=Decimal(value), bbox=BBox(x0=0.8, y0=y, x1=0.9, y1=y + 0.03), name=name, confidence=conf
    )


def test_agreement_on_price_and_item() -> None:
    s = opinion_signals(_p(350, "Борщ"), (_p(350, "борщ", conf=0.95), _p(400, "Щи", y=0.2)))
    assert s["verifier_found_price"] == s["verifier_agrees_on_item"] == s["verifier_agrees_and_confident"] == 1.0
    assert s["value_ambiguous"] == 0.0


def test_same_price_other_item_is_a_disagreement() -> None:
    s = opinion_signals(_p(350, "Борщ"), (_p(350, "Солянка"),))
    assert s["verifier_found_price"] == 1.0 and s["verifier_agrees_on_item"] == 0.0


def test_price_elsewhere_on_the_page_does_not_count() -> None:
    s = opinion_signals(_p(350, "Борщ", y=0.1), (_p(350, "Борщ", y=0.7),))
    assert s["verifier_found_price"] == 0.0
    assert s["value_ambiguous"] == 0.0


def test_repeated_value_is_flagged() -> None:
    s = opinion_signals(_p(350, "Борщ"), (_p(350, "Борщ"), _p(350, "Щи", y=0.5)))
    assert s["value_ambiguous"] == 1.0


def test_partial_and_reordered_names_agree() -> None:
    from menubench.pipeline.second_opinion import names_agree

    full = "САЛАТ «ЦЕЗАРЬ» С КУРИНОЙ ГРУДКОЙ ГРИЛЬ И ОТВАРНЫМ ЯЙЦОМ"
    assert names_agree(full, "САЛАТ «ЦЕЗАРЬ» С КУРИНОЙ")  # one line of a multi-line name
    assert names_agree("САЛАТ С МАНГО И ФИЛЕ ФОРЕЛИ", "Салат с манго и форели")  # a dropped word
    assert names_agree("Солянка сборная", "солянка сборная")
    assert names_agree("САЛАТ «ГРЕЧЕСКИЙ» С ТОМАТАМИ И ПЕЧЁНЫМ ПЕРЦЕМ", "САЛАТ «ГРЕЧЕСКИЙ»")
    assert not names_agree(full, "Салат")  # nothing distinctive: any salad would match
    assert not names_agree(full, "САЛАТ «ГРЕЧЕСКИЙ» С ТОМАТАМИ")  # a different dish


def test_anchor_pairs_repeated_prices_one_to_one() -> None:
    from menubench.pipeline.second_opinion import anchor_to_ocr

    # Twelve "$10" on a menu: the reader's boxes sit a line too high, OCR has the real places.
    reader = [_p(10, "Pizza", y=0.47), _p(10, "Taco", y=0.67)]
    ocr = (_p(10, None, y=0.70), _p(10, None, y=0.50))
    moved = anchor_to_ocr(reader, ocr)
    assert [round(m.bbox.y0, 2) for m in moved if m.bbox] == [0.5, 0.7]
    far = anchor_to_ocr([_p(10, "Pizza", y=0.1)], (_p(10, None, y=0.9),))
    assert far[0].bbox == _p(10, "Pizza", y=0.1).bbox  # too far away: keep the reader's box


def test_box_agreement_signal() -> None:
    on_spot = opinion_signals(_p(10, "Pizza", y=0.5), (_p(10, None, y=0.5),))
    a_line_off = opinion_signals(_p(10, "Pizza", y=0.47), (_p(10, None, y=0.5),))
    assert on_spot["box_on_ocr_price"] == 1.0 and on_spot["box_iou_with_ocr"] > 0.99
    assert a_line_off["box_on_ocr_price"] == 0.0 and a_line_off["box_iou_with_ocr"] < 0.3


def test_one_box_over_a_price_pair_is_on_the_price() -> None:
    reader = PricePrediction(
        page=0, value=Decimal(250), bbox=BBox(x0=0.6, y0=0.1, x1=0.8, y1=0.13), name="Чай", confidence=0.9
    )
    left_half = PricePrediction(page=0, value=Decimal(250), bbox=BBox(x0=0.6, y0=0.1, x1=0.7, y1=0.13), confidence=0.9)
    assert opinion_signals(reader, (left_half,))["box_on_ocr_price"] == 1.0
    whole_line = reader.model_copy(update={"bbox": BBox(x0=0.0, y0=0.1, x1=0.9, y1=0.13)})
    assert opinion_signals(whole_line, (left_half,))["box_on_ocr_price"] == 0.0
