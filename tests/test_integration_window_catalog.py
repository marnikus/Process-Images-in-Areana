# Integration/contract lane: real collaborators; not counted as function units.
"""S8 contract: ordered registry, real layout migration and complete re-exports."""
import importlib
import json
from html.parser import HTMLParser
from pathlib import Path
import re


from app.core import layout_service as layout

import pytest

pytestmark = pytest.mark.integration

WEB = Path(__file__).resolve().parents[1] / "app/ui/web"


def test_python_and_js_tables_identical():
    from app.core import window_catalog as catalog
    js = (WEB / "js/sash-core/constants.js").read_text()
    pairs = re.findall(r"\{\s*id:\s*'([^']+)',\s*title:\s*'([^']+)'\s*\}", js)
    assert [wid for wid, _ in pairs] == catalog.WINDOW_IDS
    assert dict(pairs) == catalog.WINDOW_TITLES
    assert catalog.WINDOW_IDS == [w["id"] for w in catalog.WINDOWS]


def test_every_registered_window_has_a_mountable_element():
    from app.core.window_catalog import WINDOW_IDS

    class Panels(HTMLParser):
        def __init__(self):
            super().__init__()
            self.panels = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "data-window" in attrs:
                self.panels.append((attrs["data-window"], attrs.get("id")))

    parser = Panels()
    parser.feed((WEB / "index.html").read_text())
    assert sorted(wid for wid, _ in parser.panels) == sorted(WINDOW_IDS)
    for wid, element in parser.panels:
        expected = "winCaptchaRecords" if wid == "recordings" else "win" + "".join(p.title() for p in wid.split("_"))
        assert element == expected


def test_ids_and_titles_have_no_duplicates_and_no_legacy_names():
    from app.core.window_catalog import WINDOW_IDS, WINDOW_TITLES
    assert len(WINDOW_IDS) == len(set(WINDOW_IDS)) == 16
    assert len(set(WINDOW_TITLES.values())) == 16
    assert "captcha_records" not in WINDOW_IDS
    assert "page_pool" not in WINDOW_IDS
    assert {"recordings", "live_debug"} <= set(WINDOW_IDS)


def test_default_tree_leaf_set_equals_the_registry():
    from app.core.window_catalog import WINDOW_IDS, default_grid_tree
    tree = default_grid_tree()
    assert sorted(layout.leaf_ids(tree)) == sorted(WINDOW_IDS)
    assert layout.validate_grid_tree(tree) is None

    def check_sizes(node):
        if node["t"] == "split":
            assert len(node["sizes"]) == len(node["children"])
            assert sum(node["sizes"]) == pytest.approx(100)
            for child in node["children"]:
                check_sizes(child)
    check_sizes(tree)


def old_tree():
    # Fixed pre-S8 registry: independent of the subject's current window list.
    ids = ["url_list", "folder", "queue", "prompt", "run", "progress", "watcher", "log",
           "settings", "captcha", "recordings", "browser", "action_blocks", "block_config", "arena_presets"]
    return {"t": "split", "dir": "col", "children": [{"t": "leaf", "id": i} for i in ids],
            "sizes": [16] + [6] * 14}


def test_grid_version_is_six_and_v5_layouts_migrate():
    from app.core.window_catalog import GRID_VERSION
    assert GRID_VERSION == 6
    tree = old_tree()
    assert layout.parse_grid_payload(json.dumps({"v": 5, "tree": tree}))[1] == "window set mismatch"
    migrated, error = layout.canonical_grid_payload(json.dumps({"v": 5, "tree": tree}))
    assert error is None
    payload = json.loads(migrated)
    assert payload["v"] == 6
    assert payload["tree"]["children"] == [tree, {"t": "leaf", "id": "live_debug"}]
    assert payload["tree"]["sizes"] == [91, 9]
    assert layout.parse_grid_payload(migrated)[1] is None
    assert layout.canonical_grid_payload(migrated) == (migrated, None)


def test_legacy_rename_still_works():
    from app.core.window_catalog import LEGACY_WINDOW_IDS
    assert LEGACY_WINDOW_IDS == {"captcha_records": "recordings"}
    tree = old_tree()
    tree["children"][10]["id"] = "captcha_records"
    migrated, error = layout.canonical_grid_payload(json.dumps({"v": 5, "tree": tree}))
    assert error is None
    original_column = json.loads(migrated)["tree"]["children"][0]
    assert original_column["sizes"] == tree["sizes"]
    assert original_column["children"][10] == {"t": "leaf", "id": "recordings"}


def test_the_layout_service_reexport_is_complete():
    from app.core import window_catalog as catalog
    for name in ("WINDOW_IDS", "WINDOW_TITLES", "WINDOWS", "GRID_VERSION", "LEGACY_WINDOW_IDS", "default_grid_tree"):
        assert getattr(layout, name) is getattr(catalog, name)
    for name in ("app.ui.panels.layout_state", "app.ui.services.undo_entries", "app.ui.services.window_preset_service"):
        importlib.import_module(name)


def test_legacy_tree_walkers_tolerate_unknown_nodes_without_mutating_them():
    node = {"t": "unknown", "children": [{"t": "leaf", "id": "recordings"}]}
    assert layout.leaf_ids(node) == []
    assert layout._rename_legacy_windows(node) is node
    assert layout._try_migrate('[1,2]', 'window set mismatch') == (None, 'window set mismatch')
