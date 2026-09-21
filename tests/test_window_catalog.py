"""S8 · one window contract, 17 windows, and the L-5 rescue (I-51).

`core/window_catalog.WINDOWS` is the ONE ordered table; `WINDOW_IDS` /
`WINDOW_TITLES` are derived (L-8 drift: the two hand-written lists disagreed
on `recordings`' position), JS `constants.js` mirrors it exactly, every
registered window has a mountable element in `index.html` (L-5: the Page
Pool markup carried an id no registry knew and `SashGrid.render()` threw it
away), `GRID_VERSION` is 7 and stored v6 layouts migrate.

RED at base: `ModuleNotFoundError: app.core.window_catalog`.
"""

import importlib
import json
import re
from pathlib import Path

import pytest

from app.core import layout_service, window_catalog as wc

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "ui" / "web"


def js_windows():
    text = (WEB / "js" / "sash-core" / "constants.js").read_text(encoding="utf-8")
    block = text.split("const WINDOWS = [", 1)[1].split("];", 1)[0]
    return re.findall(r"\{\s*id:\s*'([^']+)',\s*title:\s*'([^']+)'\s*\}", block)


def js_version():
    text = (WEB / "js" / "sash-core" / "constants.js").read_text(encoding="utf-8")
    return int(re.search(r"VERSION:\s*(\d+)", text).group(1))


def panel_id_of(win_id: str) -> str:
    """The harness rule (tests/js/sash_harness.mjs): url_list → winUrlList; recordings keeps winCaptchaRecords."""
    if win_id == "recordings":
        return "winCaptchaRecords"
    return "win" + "".join(p[:1].upper() + p[1:] for p in win_id.split("_"))


def test_python_and_js_tables_identical():
    assert [(w["id"], w["title"]) for w in wc.WINDOWS] == js_windows()
    assert wc.WINDOW_IDS == [i for i, _t in js_windows()]
    assert wc.WINDOW_TITLES == dict(js_windows())
    assert js_version() == wc.GRID_VERSION


def test_every_registered_window_has_a_mountable_element():
    """L-5 regression: a `data-window` id nobody registers is destroyed by the first grid render."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    declared = dict(re.findall(r'id="(win\w+)"\s+data-window="(\w+)"', html))
    for win_id in wc.WINDOW_IDS:
        assert declared.get(panel_id_of(win_id)) == win_id, win_id
    assert set(declared.values()) <= set(wc.WINDOW_IDS), "orphan panels (unregistered data-window ids)"
    store = (WEB / "js" / "sash-grid-windows" / "store.js").read_text(encoding="utf-8")
    for win_id in wc.WINDOW_IDS:
        assert re.search(rf"\b{win_id}:\s*'{panel_id_of(win_id)}'", store), f"store.js winElIds lacks {win_id}"


def test_ids_and_titles_have_no_duplicates_and_no_legacy_names():
    assert len(wc.WINDOW_IDS) == 17 == len(set(wc.WINDOW_IDS))
    assert len(set(wc.WINDOW_TITLES.values())) == 17
    assert "captcha_records" not in wc.WINDOW_IDS and "recordings" in wc.WINDOW_IDS
    assert "page_pool" not in wc.WINDOW_IDS and "live_debug" in wc.WINDOW_IDS  # rescued, not registered (D-21)
    assert wc.LEGACY_WINDOW_IDS == {"captcha_records": "recordings"}
    assert wc.WINDOW_TITLES["live_debug"] == "Live Worker & Queue Debug"
    assert wc.WINDOW_TITLES["job_history"] == "Job History"


def _splits(node):
    if node.get("t") == "split":
        yield node
        for kid in node["children"]:
            yield from _splits(kid)


def test_default_tree_leaf_set_equals_the_registry():
    tree = wc.default_grid_tree()
    assert sorted(layout_service.leaf_ids(tree)) == sorted(wc.WINDOW_IDS)
    for split in _splits(tree):
        assert abs(sum(split["sizes"]) - 100) < 0.01, split["sizes"]
        assert len(split["sizes"]) == len(split["children"])


def test_grid_version_is_seven_and_v6_layouts_migrate():
    assert wc.GRID_VERSION == 7
    v6_tree = json.loads(json.dumps(wc.default_grid_tree()))
    # drop the job_history leaf → the shape a v6 file on disk has (16 leaves)
    def strip(node):
        if node.get("t") != "split":
            return node
        keep = [i for i, k in enumerate(node["children"]) if not (k.get("t") == "leaf" and k["id"] == "job_history")]
        kids = [strip(node["children"][i]) for i in keep]
        total = sum(node["sizes"][i] for i in keep)
        return {**node, "children": kids, "sizes": [round(node["sizes"][i] * 100 / total, 4) for i in keep]}
    v6_tree = strip(v6_tree)
    assert "job_history" not in layout_service.leaf_ids(v6_tree)
    payload, err = layout_service.canonical_grid_payload(json.dumps({"v": 6, "tree": v6_tree}))
    assert err is None
    doc = json.loads(payload)
    assert doc["v"] == 7 and sorted(layout_service.leaf_ids(doc["tree"])) == sorted(wc.WINDOW_IDS)
    v7, err = layout_service.canonical_grid_payload(layout_service.default_payload())
    assert err is None and layout_service.canonical_grid_payload(v7) == (v7, None)  # canonical v7 is a fixed point
    assert layout_service.canonical_grid_payload(json.dumps({"v": 8, "tree": wc.default_grid_tree()}))[1] == "unsupported version 8"


def test_legacy_rename_still_works():
    tree = json.loads(json.dumps(wc.default_grid_tree()).replace('"recordings"', '"captcha_records"'))
    payload, err = layout_service.canonical_grid_payload(json.dumps({"v": 5, "tree": tree}))
    assert err is None
    migrated = json.loads(payload)["tree"]
    assert "recordings" in layout_service.leaf_ids(migrated) and "captcha_records" not in layout_service.leaf_ids(migrated)
    # position kept: the renamed leaf sits where the old one was (same path through the tree)
    def path_of(node, target, path=()):
        if node.get("t") == "leaf":
            return path if node["id"] == target else None
        for i, kid in enumerate(node["children"]):
            found = path_of(kid, target, path + (i,))
            if found is not None:
                return found
        return None
    assert path_of(migrated, "recordings") == path_of(tree, "captcha_records")


def test_the_layout_service_reexport_is_complete():
    assert layout_service.WINDOW_IDS is wc.WINDOW_IDS
    assert layout_service.WINDOWS is wc.WINDOWS
    assert layout_service.WINDOW_TITLES is wc.WINDOW_TITLES
    assert layout_service.LEGACY_WINDOW_IDS is wc.LEGACY_WINDOW_IDS
    assert layout_service.GRID_VERSION == wc.GRID_VERSION
    assert layout_service.default_grid_tree is wc.default_grid_tree
    for mod in ("app.ui.panels.layout_state", "app.ui.services.undo_entries", "app.ui.services.window_preset_service"):
        importlib.import_module(mod)
    src = (ROOT / "app" / "core" / "window_catalog.py").read_text(encoding="utf-8")
    assert "WINDOW_IDS = [w[\"id\"] for w in WINDOWS]" in src  # derived, never hand-written (L-8)
