"""Grid layout persistence — window-set parity, round-trip, migration, rejection.

Regression tests for the 13-vs-14 desync (Python WINDOW_IDS missed 'captcha'
while sash-core.js had it): every 14-window save was silently substituted
with the 13-window default, and preset load returned an envelope the JS
preview could not validate (RULE 8: real layout_service + real bridge
methods against an isolated config dir).
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.layout_service import (
    WINDOW_IDS,
    WINDOW_TITLES,
    canonical_grid_payload,
    default_grid_tree,
    default_payload,
    leaf_ids,
)
from app.persistence.config_manager import ConfigManager
from app.ui.bridge import Bridge

ROOT = Path(__file__).resolve().parent.parent
SASH_CORE = ROOT / "app" / "ui" / "web" / "js" / "sash-core.js"


def js_windows():
    """The real JS window set, parsed from the WINDOWS block (not layouts)."""
    text = SASH_CORE.read_text(encoding="utf-8")
    block = text.split("const WINDOWS = [", 1)[1].split("];", 1)[0]
    return re.findall(r"\{\s*id:\s*'([^']+)',\s*title:\s*'([^']+)'\s*\}", block)


def col_with(tree, leaf_id):
    """Find the col split directly containing a leaf (or None)."""
    found = None

    def walk(node):
        nonlocal found
        if not isinstance(node, dict) or node.get("t") != "split":
            return
        if node.get("dir") == "col":
            kids = [k.get("id") for k in node.get("children", [])]
            if leaf_id in kids:
                found = node
                return
        for kid in node.get("children", []):
            walk(kid)

    walk(tree)
    return found


def make_fake(config_dir):
    """Bridge methods bound to a stub (no Qt event loop needed)."""
    logs = []

    class FakeSignal:
        def emit(self, *a):
            pass

    fake = SimpleNamespace(
        config=ConfigManager(str(config_dir)),
        _log=lambda m, level="info": logs.append((level, m)),
        grid_layout_changed=FakeSignal(),
        grid_layout_persisted=FakeSignal(),
        window_preset_list_updated=FakeSignal(),
        undo_service=SimpleNamespace(push=lambda *a: None),
        _emit_undo_state=lambda: None,
    )
    for helper in ("_parse_preset_input", "_extract_from_portable",
                   "_extract_tree_from_grid", "_extract_payload_from_grid",
                   "_build_preset_doc", "list_window_presets",
                   "get_grid_layout"):
        setattr(fake, helper, getattr(Bridge, helper).__get__(fake))
    return fake, logs


def portable_doc(tree, name="Desk"):
    ids = leaf_ids(tree)
    return {"format": "chat-v-bot.window-preset", "schema_version": 1,
            "app_version": "0.1.0", "name": name,
            "created_at": "t", "updated_at": "t",
            "grid": {"type": "sash-tree", "version": 4,
                     "window_count": len(ids), "sizes_unit": "percent",
                     "tree": tree},
            "windows": [{"id": i} for i in ids],
            "window_states": {"closed": [], "minimized": []},
            "screen": {"width": 1, "height": 1, "device_pixel_ratio": 1}}


@pytest.mark.unit
def test_window_set_matches_js():
    pairs = js_windows()
    assert [i for i, _ in pairs] == WINDOW_IDS  # order + ids identical
    assert {i: t for i, t in pairs} == WINDOW_TITLES  # titles identical


@pytest.mark.unit
def test_default_payload_valid_with_captcha():
    payload, err = canonical_grid_payload(default_payload())
    assert err is None
    ids = leaf_ids(json.loads(payload)["tree"])
    assert sorted(ids) == sorted(WINDOW_IDS)
    assert "captcha" in ids


@pytest.mark.unit
def test_default_tree_mirrors_js_captcha_column():
    col = col_with(default_grid_tree(), "captcha")
    assert col is not None
    assert [k.get("id") for k in col["children"]] == ["prompt", "run", "settings", "captcha"]
    assert col["sizes"] == [40, 22, 26, 12]


@pytest.mark.unit
def test_user_layout_round_trips_verbatim():
    tree = default_grid_tree()
    left = tree["children"][0]["children"][0]["children"]
    left[0], left[1] = left[1], left[0]  # user drags url_list below folder
    payload = json.dumps({"v": 4, "tree": tree}, separators=(",", ":"))
    out, err = canonical_grid_payload(payload)
    assert err is None
    assert leaf_ids(json.loads(out)["tree"]) == leaf_ids(tree)
    assert out != default_payload()  # never substituted


@pytest.mark.unit
def test_legacy_13_window_payload_migrates():
    tree = default_grid_tree()
    col = col_with(tree, "captcha")
    idx = [k.get("id") for k in col["children"]].index("captcha")
    del col["children"][idx]
    col["sizes"] = [44, 24, 32]  # renormalized, sums to 100
    assert "captcha" not in leaf_ids(tree)
    out, err = canonical_grid_payload(json.dumps({"v": 4, "tree": tree}))
    assert err is None
    ids = leaf_ids(json.loads(out)["tree"])
    assert sorted(ids) == sorted(WINDOW_IDS)  # captcha appended


@pytest.mark.unit
def test_legacy_14_window_payload_gains_recordings():
    """Old 14-window layouts predate the Recordings window (#15): migration
    appends it instead of rejecting or default-substituting (RULE 13)."""
    tree = default_grid_tree()
    col = col_with(tree, "recordings")
    idx = [k.get("id") for k in col["children"]].index("recordings")
    del col["children"][idx]
    col["sizes"] = [30, 25, 22, 23]  # renormalized, sums to 100
    assert "recordings" not in leaf_ids(tree)
    out, err = canonical_grid_payload(json.dumps({"v": 4, "tree": tree}))
    assert err is None
    ids = leaf_ids(json.loads(out)["tree"])
    assert sorted(ids) == sorted(WINDOW_IDS)  # recordings appended
    assert "recordings" in ids


@pytest.mark.unit
def test_unknown_window_rejected_not_defaulted():
    tree = default_grid_tree()
    col = col_with(tree, "captcha")
    col["children"][-1]["id"] = "evil"
    out, err = canonical_grid_payload(json.dumps({"v": 4, "tree": tree}))
    assert out is None  # RULE 13: rejected, never default-substituted
    assert err == "window set mismatch"


@pytest.mark.unit
def test_corrupt_payloads_rejected():
    out, err = canonical_grid_payload("not json")
    assert out is None and "bad JSON" in err
    out, err = canonical_grid_payload('{"v": 4}')
    assert out is None and err


@pytest.mark.unit
def test_save_grid_layout_stores_user_tree(isolated_config_dir):
    fake, _ = make_fake(isolated_config_dir)
    tree = default_grid_tree()
    left = tree["children"][0]["children"][0]["children"]
    left[0], left[1] = left[1], left[0]
    payload = json.dumps({"v": 4, "tree": tree}, separators=(",", ":"))
    assert Bridge.save_grid_layout(fake, payload) is True
    stored = fake.config.get_state("grid_layout")
    assert leaf_ids(json.loads(stored)["tree"]) == leaf_ids(tree)


@pytest.mark.unit
def test_save_rejects_unknown_window_and_keeps_old(isolated_config_dir):
    fake, logs = make_fake(isolated_config_dir)
    good = default_payload()
    assert Bridge.save_grid_layout(fake, good) is True
    tree = json.loads(good)["tree"]
    col_with(tree, "captcha")["children"][-1]["id"] = "evil"
    bad = json.dumps({"v": 4, "tree": tree}, separators=(",", ":"))
    assert Bridge.save_grid_layout(fake, bad) is False
    expect, _ = canonical_grid_payload(good)
    assert fake.config.get_state("grid_layout") == expect  # old kept
    assert any("rejected" in m for _, m in logs)


@pytest.mark.unit
def test_window_states_keep_captcha(isolated_config_dir):
    fake, _ = make_fake(isolated_config_dir)
    states = json.dumps({"closed": ["captcha"], "minimized": []})
    assert Bridge.save_window_states(fake, states) is True
    assert json.loads(Bridge.get_window_states(fake)) == {"closed": ["captcha"], "minimized": []}


@pytest.mark.unit
def test_preset_save_load_round_trip(isolated_config_dir):
    fake, _ = make_fake(isolated_config_dir)
    tree = default_grid_tree()
    res = json.loads(Bridge.save_window_preset(fake, "Desk", json.dumps(portable_doc(tree))))
    assert res == {"ok": True, "name": "Desk"}
    doc = fake.config.window_presets.load_preset("Desk")
    assert doc["grid"]["window_count"] == 15
    assert len(leaf_ids(json.loads(doc["grid"]["payload"])["tree"])) == 15
    assert len(leaf_ids(doc["grid"]["tree"])) == 15
    # load returns the portable doc (JS preview contract), applies nothing
    sentinel = json.dumps({"v": 4, "tree": default_grid_tree()}, separators=(",", ":"))
    Bridge.save_grid_layout(fake, sentinel)
    loaded = json.loads(Bridge.load_window_preset(fake, "Desk"))
    assert loaded["format"] == "chat-v-bot.window-preset"
    assert len(leaf_ids(loaded["grid"]["tree"])) == 15
    expect, _ = canonical_grid_payload(sentinel)
    assert fake.config.get_state("grid_layout") == expect  # untouched


@pytest.mark.unit
def test_load_missing_or_broken_preset_errors(isolated_config_dir):
    fake, _ = make_fake(isolated_config_dir)
    res = json.loads(Bridge.load_window_preset(fake, "Nope"))
    assert res["ok"] is False and "not found" in res["error"]
    fake.config.window_presets.save_preset("Broken", {"name": "Broken", "grid": {}})
    res = json.loads(Bridge.load_window_preset(fake, "Broken"))
    assert res["ok"] is False
    fake.config.window_presets.save_preset(
        "BadTree", {"name": "BadTree", "grid": {"tree": {"t": "leaf"}}})
    res = json.loads(Bridge.load_window_preset(fake, "BadTree"))
    assert res["ok"] is False
