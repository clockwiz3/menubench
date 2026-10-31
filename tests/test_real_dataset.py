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


def test_import_and_split_keep_venues_together(tmp_path: Path) -> None:
    from menubench.data.real import import_folder

    store = RealStore(tmp_path)
    for name in ("a1.jpg", "a2.jpg", "b1.jpg", "c1.jpg", "c2.jpg", "seen.jpg", "x.jpg"):
        (tmp_path / name).write_bytes(_jpeg())
    config = {
        "exclude": {"x.jpg": "not a menu"},
        "groups": {
            "venue-a": {"files": ["a1.jpg", "a2.jpg"], "tags": ["photo"]},
            "venue-b": {"files": ["b1.jpg"]},
            "venue-c": {"files": ["c1.jpg", "c2.jpg"]},
            "tuned-on": {"files": ["seen.jpg"], "pin": "dev"},
        },
    }
    report = import_folder(store, config)
    assert len(report["imported"]) == 6 and len(report["excluded"]) == 1
    assert (tmp_path / "_originals" / "a1.jpg").exists() and (tmp_path / "_excluded" / "x.jpg").exists()
    assert not import_folder(store, config)["imported"]  # nothing left to import, nothing duplicated
    for m in store.ids():
        _finish(store, m)
    splits = assign_splits(store, dev=2, seed=3)
    by_group: dict[str, set[str]] = {}
    for m, split in splits.items():
        by_group.setdefault(store.meta(m).group or m, set()).add(split)
    assert all(len(s) == 1 for s in by_group.values())  # a venue never straddles dev and test
    assert by_group["tuned-on"] == {"real-dev"}
    assert any(s == {"real-test"} for s in by_group.values())
    tagged = [m for m in store.ids() if store.meta(m).group == "venue-a"]
    assert all(store.annotation(m).tags == ("photo",) for m in tagged)


def test_real_report_tables(tmp_path: Path) -> None:
    from menubench.report import real_report

    store = RealStore(tmp_path)
    ids = [store.create([("m.jpg", _jpeg())]) for _ in range(3)]
    for i, m in enumerate(ids):
        _finish(store, m)
        ann = store.annotation(m).model_copy(update={"tags": ("photo", "angled") if i == 0 else ("screenshot",)})
        store.save(ann, group="cafe-a" if i < 2 else "cafe-b")
    assert "No evaluated runs" in real_report({}, {}, "real-test", tmp_path)

    op = {"auto_placed": 2, "risk": 0.0, "recall": 0.67, "box_off": 0.0}
    metrics = {
        "gt_prices": 3,
        "pair": {"f1": 0.9},
        "operating_point": op,
        "cost": {"per_menu_usd": 0.004},
        "slices": {"tag": {"photo": {"menus": 1, "gt_prices": 1, "pair": {"f1": 1.0}, "operating_point": op}}},
        "per_menu": {m: {"gt": 1, "pair_tp": 1, "errors": 0} for m in ids},
    }
    synthetic = {**metrics, "pair": {"f1": 0.97}}
    text = real_report(
        {"second-opinion-claude-cal": (None, metrics)},  # type: ignore[dict-item]
        {"second-opinion-claude-cal": (None, synthetic)},  # type: ignore[dict-item]
        "real-test",
        tmp_path,
    )
    assert "| 3 | 3 | 2 | 3 | 3 |" in text  # menus, pages, venues, items, prices
    assert "| angled | 1 | 1 |" in text
    assert "## Synthetic vs real" in text and "| 97.0 | 90.0 |" in text
    assert "– (n=2)" in text  # two auto-placed prices are too few for a rate
    assert "| cafe-a | 2 | 2 | 100.0 | 0 |" in text


def test_export_release(tmp_path: Path) -> None:
    import json

    from menubench.data.export import ExportError, export_release

    store = RealStore(tmp_path / "real")
    photo, online, bare = (store.create([("m.jpg", _jpeg())]) for _ in range(3))
    for m, group in ((photo, "cafe-a"), (online, "cafe-b"), (bare, "cafe-c")):
        _finish(store, m)
        store.save(store.annotation(m), group=group)
    store.save(store.annotation(online), source_url="https://example.com/menu")
    store.save(store.annotation(bare).model_copy(update={"tags": ("screenshot",)}))

    out = tmp_path / "release"
    with pytest.raises(ExportError):
        export_release(store, out)  # the split is not fixed yet
    assign_splits(store, dev=0, seed=7)
    report = export_release(store, out)

    assert report.rows == {"photos/dev": 0, "online/dev": 0, "photos/test": 1, "online/test": 1}
    assert report.skipped == [(bare, "screenshot without a source link")]
    [row] = [json.loads(line) for line in (out / "photos/test/metadata.jsonl").read_text(encoding="utf-8").splitlines()]
    assert row["file_name"] == f"{photo}-p0.jpg" and (out / "photos/test" / row["file_name"]).exists()
    assert row["venue_id"] == "v01" and row["prices"][0]["value"] == "350" and row["prices"][0]["item_ids"] == ["i1"]
    with Image.open(out / "photos/test" / row["file_name"]) as img:
        assert not img.getexif()
    [web] = [json.loads(line) for line in (out / "online/test.jsonl").read_text(encoding="utf-8").splitlines()]
    assert web["source_url"] == "https://example.com/menu" and "file_name" not in web
    # Venue ids survive the next release.
    export_release(store, out)
    assert json.loads((store.root / "venues.json").read_text(encoding="utf-8"))["cafe-a"] == "v01"


def test_source_url_must_be_a_web_address() -> None:
    from pydantic import ValidationError

    from menubench.server.annotate_api import MenuDraft

    base = {"lang": "sr", "items": [], "prices": [], "status": "prelabeled"}
    assert MenuDraft(**base, source_url="  ").source_url is None
    assert MenuDraft(**base, source_url="https://cafe.rs/meni").source_url == "https://cafe.rs/meni"
    with pytest.raises(ValidationError):
        MenuDraft(**base, source_url="javascript:alert(1)")
