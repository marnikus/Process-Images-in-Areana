"""core.window_catalog — ONE ordered window table, mirrored exactly by JS (S8, D-20/D-21, I-51).

16 windows (the Live Worker & Queue Debug window is #16), ids and titles
derived from one list, GRID_VERSION 6 with v5 layouts migrating, and the L-5
rescue: every `data-window` in index.html is a registered window (the Page
Pool markup used to sit in an orphan `page_pool` panel that `SashGrid.render()`
discarded).
"""

import importlib
import json
import re
from pathlib import Path

import pytest

from app.core import layout_service, window_catalog

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "ui" / "web"


def js_windows():
    text = (WEB / "js" / "sash-core" / "constants.js").read_text(encoding="utf-8")
    block = text.split("const WINDOWS = [", 1)[1].split("];", 1)[0]
    return re.findall(r"id:\s*'([^']+)',\s*title:\s*'([^']+)'", block)


def test_python_and_js_tables_identical():
    pairs = js_windows()
    assert [i for i, _ in pairs] == window_catalog.WINDOW_IDS          # ids AND order
    assert {i: t for i, t in pairs} == window_catalog.WINDOW_TITLES
    assert len(pairs) == 16 and pairs[-1] == ("live_debug", "Live Worker & Queue Debug")
    text = (WEB / "js" / "sash-core" / "constants.js").read_text(encoding="utf-8")
    assert f"VERSION: {window_catalog.GRID_VERSION}" in text


def test_every_registered_window_has_a_mountable_element_and_no_orphan():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    mounted = re.findall(r'data-window="([^"]+)"', html)
    assert sorted(mounted) == sorted(window_catalog.WINDOW_IDS)          # L-5: no orphan panel, none missing
    assert 'id="winLiveDebug" data-window="live_debug"' in html
    assert "page_pool" not in mounted
    for pool_id in ("poolStatusBadge", "poolRefreshBtn", "poolConnectBtn", "poolClearBtn", "poolTableBody"):
        assert f'id="{pool_id}"' in html                                  # the rescued markup kept its ids


def test_ids_and_titles_have_no_duplicates_and_no_legacy_names():
    ids = window_catalog.WINDOW_IDS
    assert len(ids) == len(set(ids)) == 16
    assert "captcha_records" not in ids and "recordings" in ids
    assert window_catalog.LEGACY_WINDOW_IDS == {"captcha_records": "recordings"}
    assert window_catalog.WINDOW_IDS == [w["id"] for w in window_catalog.WINDOWS]   # derived, never hand-written
    assert window_catalog.WINDOW_TITLES == {w["id"]: w["title"] for w in window_catalog.WINDOWS}


def _splits(node):
    if node.get("t") == "split":
        yield node
        for k in node["children"]:
            yield from _splits(k)


def test_default_tree_leaf_set_equals_the_registry():
    tree = window_catalog.default_grid_tree()
    assert sorted(layout_service.leaf_ids(tree)) == sorted(window_catalog.WINDOW_IDS)
    for split in _splits(tree):
        assert abs(sum(split["sizes"]) - 100) < 0.01, split["sizes"]
        assert len(split["sizes"]) == len(split["children"])


def test_grid_version_is_six_and_v5_layouts_migrate():
    assert window_catalog.GRID_VERSION == 6
    v5_tree = json.loads(layout_service.default_payload())["tree"]
    v5_tree = _drop_leaf(v5_tree, "live_debug")
    assert len(layout_service.leaf_ids(v5_tree)) == 15
    payload, err = layout_service.canonical_grid_payload(json.dumps({"v": 5, "tree": v5_tree}))
    assert err is None
    doc = json.loads(payload)
    assert doc["v"] == 6 and sorted(layout_service.leaf_ids(doc["tree"])) == sorted(window_catalog.WINDOW_IDS)
    again, err2 = layout_service.canonical_grid_payload(payload)
    assert err2 is None and again == payload                                # a v6 payload round-trips


def _drop_leaf(node, wid):
    if node.get("t") == "leaf":
        return node
    kids = [_drop_leaf(k, wid) for k in node["children"] if not (k.get("t") == "leaf" and k.get("id") == wid)]
    if len(kids) != len(node["children"]):
        share = round(100 / len(kids), 4)
        sizes = [share] * len(kids)
        sizes[0] = round(100 - share * (len(kids) - 1), 4)
        return {**node, "children": kids, "sizes": sizes}
    return {**node, "children": kids}


def test_legacy_rename_still_works():
    tree = json.loads(layout_service.default_payload())["tree"]
    text = json.dumps(tree).replace('"recordings"', '"captcha_records"')
    payload, err = layout_service.canonical_grid_payload(json.dumps({"v": 5, "tree": json.loads(text)}))
    assert err is None
    assert "captcha_records" not in payload and '"recordings"' in payload


def test_the_layout_service_reexport_is_complete():
    assert layout_service.WINDOW_IDS is window_catalog.WINDOW_IDS
    assert layout_service.WINDOWS is window_catalog.WINDOWS
    assert layout_service.WINDOW_TITLES is window_catalog.WINDOW_TITLES
    assert layout_service.GRID_VERSION == window_catalog.GRID_VERSION
    assert layout_service.default_grid_tree is window_catalog.default_grid_tree
    for mod in ("app.ui.panels.layout_state", "app.ui.services.undo_entries",
                "app.ui.services.window_preset_service"):
        importlib.import_module(mod)
    assert "WINDOWS = [" not in (ROOT / "app/core/layout_service.py").read_text(encoding="utf-8")


def test_unknown_window_ids_are_rejected_not_migrated_and_rename_ignores_foreign_nodes():
    """A stored tree naming a window no registry knows is refused (never default-substituted)."""
    tree = json.loads(layout_service.default_payload())["tree"]
    bogus = json.loads(json.dumps(tree).replace('"live_debug"', '"bogus_win"'))
    payload, err = layout_service.canonical_grid_payload(json.dumps({"v": 5, "tree": bogus}))
    assert payload is None and err == "window set mismatch"
    assert layout_service._rename_legacy_windows({"t": "weird"}) == {"t": "weird"}
    assert layout_service._rename_legacy_windows(3) == 3
    # a mismatch whose stored tree is not even an object stays rejected with the original error
    assert layout_service._try_migrate(json.dumps({"v": 5, "tree": [1, 2]}), "window set mismatch") == (None, "window set mismatch")
