"""Layout panel + services tests (A5.1): serialize, preset docs, arena emit."""

import json
from types import SimpleNamespace

import pytest

from app.core.layout_service import default_grid_tree, leaf_ids
from app.ui.panels import layout_state as panel
from app.ui.services import arena_serialize as js
from app.ui.services import window_preset_service as presets


def state_dict():
    return {
        "version": 1,
        "urls": [{"id": "u1", "url": "https://a", "enabled": True,
                  "last_status": "ready", "error": "", "last_checked": "t",
                  "tab_id": "t1"}],
        "images": [{"id": "i1", "relative_path": "a.png",
                    "absolute_path": "/x/a.png", "filename": "a.png",
                    "status": "completed", "selected": True,
                    "assigned_url_id": "u1", "attempt_count": 1,
                    "output_path": "/x/a_AI.png", "error": "", "size": 10}],
        "folder": {"path": "/x"},
        "prompt": {"user_prompt": "draw"},
        "settings": {"timeouts": {"page_load": 5, "generation": 9},
                     "output": {"suffix": "_AI", "overwrite": True},
                     "highlight": {"duration_seconds": 2}, "browser": {"h": 1},
                     "retries": {"max_attempts": 2}, "concurrency": 3},
        "progress": {"pct": 50}, "run_state": "idle", "jobs": [{"j": 1}],
    }


def test_serialize_sections():
    d = state_dict()
    assert js.urls_to_js(d)[0]["status"] == "ready"
    assert js.images_to_js(d)[0]["attempts"] == 1
    assert js.prompt_to_js(d) == {"template": "draw"}
    s = js.settings_to_js(d)
    assert (s["timeout_seconds"], s["generation_timeout"], s["max_retries"]) == (5, 9, 2)
    assert s["naming_suffix"] == "_AI" and s["max_concurrent"] == 3
    full = js.arena_to_js(SimpleNamespace(to_dict=lambda: d))
    assert full["run_state"] == "idle" and full["jobs"] == [{"j": 1}]
    assert full["folder"] == {"path": "/x"}


def portable(tree):
    ids = leaf_ids(tree)
    return {"format": "chat-v-bot.window-preset", "grid": {"tree": tree, "version": 4},
            "window_states": {"closed": ["captcha"], "minimized": []}}


def test_parse_and_build_round_trip():
    tree = default_grid_tree()
    t, payload, ws, doc, err = presets.parse_preset_input(json.dumps(portable(tree)))
    assert err is None and payload and ws["closed"] == ["captcha"]
    assert leaf_ids(t) == leaf_ids(tree)
    out = presets.build_preset_doc("D", payload, {"tree": t, "ws": ws, "incoming": doc,
                                                   "stored_ws": {"closed": [], "minimized": []}})
    assert out["format"] == "chat-v-bot.window-preset" and out["name"] == "D"
    assert out["window_states"]["closed"] == ["captcha"]


def test_parse_rejects_shapes():
    assert presets.parse_preset_input("")[0] is None
    assert presets.parse_preset_input("nope")[4].startswith("bad JSON")
    assert presets.parse_preset_input("[1]")[4] == "payload must be object"
    assert presets.parse_preset_input("{}")[1] is None  # unknown shape, no crash


def test_save_preset_doc_fallback_and_errors():
    tree = default_grid_tree()
    raw = json.dumps({"v": 4, "tree": tree})
    doc, err = presets.save_preset_doc("D", raw, raw, {"closed": [], "minimized": []})
    assert err is None and doc["name"] == "D" and "format" not in doc
    doc2, err2 = presets.save_preset_doc("D", "junk", raw, {})
    assert err2 is None and doc2["name"] == "D"  # fallback layout used
    _, err3 = presets.save_preset_doc("D", "junk", "junk", {})
    assert err3  # nothing valid anywhere


def test_load_preset_doc_paths():
    payload, err = presets.load_preset_doc(None, "Nope")
    assert payload is None and "not found" in err
    _, err = presets.load_preset_doc({"name": "B", "grid": {}}, "B")
    assert "unsupported" in err
    tree = default_grid_tree()
    doc = {"name": "D", "grid": {"tree": tree, "version": 4}}
    payload, err = presets.load_preset_doc(doc, "D")
    assert err is None and json.loads(payload)["name"] == "D"


def fake_bridge(tmp_path):
    emitted = {}

    class Sig:
        def __init__(self, name):
            self.name = name

        def emit(self, *a):
            emitted[self.name] = a

    return SimpleNamespace(
        state=SimpleNamespace(to_dict=state_dict),
        state_path=str(tmp_path / "arena.json"),
        config=SimpleNamespace(window_presets=SimpleNamespace(
            load_preset=lambda n: {"name": n} if n == "D" else None)),
        _run_state="running",
        _exported_paths={},
        _log=lambda m, l="info": emitted.setdefault("logs", []).append(m),
        arena_log=Sig("log"), arena_state_updated=Sig("arena"),
        progress_updated=Sig("prog"),
    ), emitted


def test_save_and_emit_arena(tmp_path):
    bridge, emitted = fake_bridge(tmp_path)
    panel.save_arena_state(bridge)
    assert (tmp_path / "arena.json").exists()
    assert json.loads(emitted["arena"][0])["run_state"] == "idle"
    assert json.loads(emitted["prog"][0])["run_state"] == "running"  # live override


def test_export_import_headless(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(panel, "QFileDialog", None)
    bridge, _ = fake_bridge(tmp_path)
    (tmp_path / "config").mkdir()
    res = json.loads(panel.export_preset_file(bridge, "D"))
    assert res["ok"] is True and bridge._exported_paths["D"].endswith("D_window.json")
    res = json.loads(panel.export_preset_file(bridge, "Nope"))
    assert res["ok"] is False
    res = json.loads(panel.import_preset_file(bridge))
    assert res["ok"] is False and "headless" in res["error"]
