import io
from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image

from menubench.data.real import RealStore, SplitError, Status, assign_splits, create_recheck
from menubench.eval.agreement import self_agreement
from menubench.schema import BBox, MenuItem, PriceAnnotation


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _finish(store: RealStore, menu_id: str, value: int = 350, name: str = "Ćevapi") -> None:
    box = BBox(x0=0.6, y0=0.1, x1=0.8, y1=0.14)
    ann = store.annotation(menu_id).model_copy(
        update={
            "items": (MenuItem(id="i1", page=0, name=name, bbox=box),),
            "prices": (PriceAnnotation(id="p1", page=0, value=Decimal(value), bbox=box, item_ids=("i1",)),),
        }
    )
    store.save(ann, status=Status.ANNOTATED)


def test_split_is_reproducible_and_locked(tmp_path: Path) -> None:
    store = RealStore(tmp_path)
    ids = [store.create([("m.jpg", _jpeg())]) for _ in range(6)]
    for m in ids:
        _finish(store, m)
    first = assign_splits(store, dev=2, seed=7)
    assert sorted(first.values()).count("real-dev") == 2
    assert all(store.meta(m).split_locked for m in ids)
    with pytest.raises(SplitError):
        assign_splits(store, dev=2, seed=7)  # test must not be reshuffled silently
    index = (tmp_path / "index.jsonl").read_text(encoding="utf-8")
    assert index.count("real-dev") == 2 and index.count("real-test") == 4


def test_blind_recheck_and_self_agreement(tmp_path: Path) -> None:
    store = RealStore(tmp_path)
    menu = store.create([("m.jpg", _jpeg())], lang="sr")
    _finish(store, menu)
    copy = create_recheck(store, menu)
    assert store.annotation(copy).prices == ()  # nothing to peek at
    _finish(store, copy, name="Ćevapi")
    assert copy not in (tmp_path / "index.jsonl").read_text(encoding="utf-8")  # never part of evaluation
    result = self_agreement(store)
    assert result["menus"] == 1 and result["pair_agreement"] == 1.0

    other = store.create([("m.jpg", _jpeg())])
    _finish(store, other)
    _finish(store, create_recheck(store, other), name="Pljeskavica")  # same price, different item
    assert self_agreement(store)["pair_agreement"] == 0.5
