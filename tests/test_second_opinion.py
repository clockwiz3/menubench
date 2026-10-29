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
