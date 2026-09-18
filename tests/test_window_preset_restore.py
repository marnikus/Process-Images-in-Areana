"""Window preset restore (2026-09-18 window-preset-restore).

load_window_preset must return the FULL portable document (JS validation
rejects anything without `format` — the old envelope answer caused
'unsupported window preset format or schema version' for every preset) and
must NOT touch the session's saved layout: previewing a preset is a read,
applying is JS-side applyPortablePreset (which persists via the save path).

Legacy slim docs (pre-portable-format) must be upgraded to the full portable
shape so they preview + restore too.
Docs: docs/archive/2026-09-18-window-preset-restore/design.md
"""

import json
from pathlib import Path

import pytest

from app.core.layout_service import default_payload
from app.persistence.config_manager import ConfigManager
import app.ui.bridge as bridge_mod
from app.ui.bridge import Bridge, PRESET_FORMAT, PRESET_SCHEMA_VERSION

LEGACY_DOC = {
    "name": "Old layout",
    "grid": {"payload": default_payload()},
    "window_states": {"closed": ["log"], "minimized": ["progress"]},
    "updated_at": "2026-08-01T00:00:00Z",
    "app_version": "arena-0.9",
}


def _make_bridge(tmp_path: Path) -> Bridge:
    cfg = ConfigManager(config_dir=str(tmp_path / "config"))
    return Bridge(cfg, tmp_path / "app_state.json")


def _upgrade(bridge: Bridge, doc):
    return bridge._upgrade_preset_doc(doc)


@pytest.mark.unit
def test_upgrade_legacy_doc_to_full_portable(tmp_path):
    bridge = _make_bridge(tmp_path)
    full = _upgrade(bridge, dict(LEGACY_DOC, grid={"payload": default_payload()}))
    assert full is not None
    assert full["format"] == PRESET_FORMAT
    assert full["schema_version"] == PRESET_SCHEMA_VERSION
    assert full["name"] == "Old layout"
    assert full["app_version"] == "arena-0.9"
    assert len(full["windows"]) == 14
    states = {w["id"]: w["state"] for w in full["windows"]}
    assert states["log"] == "closed"
    assert states["progress"] == "minimized"
    assert states["prompt"] == "open"
    assert all(w["bounds"] == {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0} for w in full["windows"])
    assert full["window_states"] == {"closed": ["log"], "minimized": ["progress"]}
    assert full["screen"]["synthetic"] is True
    assert full["grid"]["window_count"] == 14
    assert full["grid"]["payload"] and isinstance(full["grid"]["tree"], dict)


@pytest.mark.unit
def test_upgrade_drops_unknown_and_overlapping_states(tmp_path):
    bridge = _make_bridge(tmp_path)
    doc = dict(LEGACY_DOC)
    doc["window_states"] = {"closed": ["log", "bogus_window"], "minimized": ["log", "settings"]}
    full = _upgrade(bridge, doc)
    assert full["window_states"] == {"closed": ["log"], "minimized": ["settings"]}
    states = {w["id"]: w["state"] for w in full["windows"]}
    assert states["log"] == "closed" and states["settings"] == "minimized"


@pytest.mark.unit
def test_upgrade_passthrough_and_rejects(tmp_path):
    bridge = _make_bridge(tmp_path)
    portable = dict(LEGACY_DOC, format=PRESET_FORMAT, schema_version=1)
    assert _upgrade(bridge, portable) is portable  # already full — pass through
    assert _upgrade(bridge, None) is None
    assert _upgrade(bridge, {"name": "x", "grid": {}}) is None
    assert _upgrade(bridge, {"name": "x", "grid": {"payload": "not json"}}) is None


@pytest.mark.unit
def test_load_window_preset_returns_document_without_side_effects(tmp_path):
    bridge = _make_bridge(tmp_path)
    bridge.config.window_presets.save_preset("P1", dict(LEGACY_DOC, grid={"payload": default_payload()}))
    # sentinel session state that a preview must NOT touch (the 12:34 desync bug)
    bridge.config.set_state(grid_layout="SENTINEL", window_states={"closed": [], "minimized": ["run"]})
    resp = json.loads(bridge.load_window_preset("P1"))
    assert resp["ok"] is True
    assert resp["document"]["format"] == PRESET_FORMAT  # the validator's first check
    assert bridge.config.get_state("grid_layout") == "SENTINEL"
    assert bridge.config.get_state("window_states") == {"closed": [], "minimized": ["run"]}


@pytest.mark.unit
def test_load_window_preset_not_found_and_invalid(tmp_path):
    bridge = _make_bridge(tmp_path)
    assert json.loads(bridge.load_window_preset("NOPE"))["ok"] is False
    bridge.config.window_presets.save_preset("BAD", {"name": "bad", "grid": {}})
    assert json.loads(bridge.load_window_preset("BAD"))["ok"] is False


@pytest.mark.unit
def test_export_writes_upgraded_document(tmp_path, monkeypatch):
    bridge = _make_bridge(tmp_path)
    bridge.config.window_presets.save_preset("LEG", dict(LEGACY_DOC, grid={"payload": default_payload()}))
    monkeypatch.setattr(bridge_mod, "QFileDialog", None)  # headless export path
    monkeypatch.chdir(tmp_path)
    resp = json.loads(bridge.export_window_preset("LEG"))
    assert resp["ok"] is True
    exported = json.loads(Path(resp["path"]).read_text(encoding="utf-8"))
    assert exported["format"] == PRESET_FORMAT  # round-trips strict import validation
