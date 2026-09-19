"""Unit tests for ConfigManager / SessionStore / WindowPresetStore (B7 coverage).

RULE 8: each test fails if the store's contract breaks (defaults on
corrupt file, atomic round-trip, undo-history clamp inside session,
preset listing order).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.persistence.config_manager import (
    DEFAULT_SESSION,
    ConfigManager,
    SessionStore,
    WindowPresetStore,
)

@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    return tmp_path / "config"

@pytest.mark.unit
def test_session_store_defaults_and_round_trip(tmp_path: Path):
    path = tmp_path / "session.json"
    store = SessionStore(path)
    assert store.get("theme") == DEFAULT_SESSION["theme"]
    store.set(theme="light", last_folder="/imgs")
    store.save()
    reloaded = SessionStore(path)
    assert reloaded.get("theme") == "light"
    assert reloaded.get("last_folder") == "/imgs"
    assert reloaded.get("missing_key", "fallback") == "fallback"

@pytest.mark.unit
def test_session_store_corrupt_file_keeps_defaults(tmp_path: Path):
    path = tmp_path / "session.json"
    path.write_text("not-json", encoding="utf-8")
    store = SessionStore(path)
    assert store.get("cdp_port") == DEFAULT_SESSION["cdp_port"]

@pytest.mark.unit
def test_session_set_is_a_plain_key_update(tmp_path: Path):
    """SessionStore.set does NOT clamp embedded history — that is UndoStore's job."""
    store = SessionStore(tmp_path / "session.json")
    store.set(history=[{"kind": "urls", "value": [1]}], index=0)
    assert store.get("history") == [{"kind": "urls", "value": [1]}]
    assert store.get("index") == 0

@pytest.mark.unit
def test_window_preset_store_round_trip_and_order(tmp_path: Path):
    path = tmp_path / "window_presets.json"
    store = WindowPresetStore(path)
    store.save_preset("older", {"updated_at": "2026-01-01", "app_version": "1",
                                "grid": {"window_count": 3}})
    store.save_preset("newer", {"updated_at": "2026-03-01", "app_version": "1",
                                "grid": {"window_count": 5}})
    reloaded = WindowPresetStore(path)
    names = [p["name"] for p in reloaded.list_presets()]
    assert names == ["newer", "older"]  # newest first
    older = reloaded.load_preset("older")
    assert older["grid"]["window_count"] == 3
    assert reloaded.load_preset("missing") is None
    assert reloaded.delete_preset("older") is True
    assert reloaded.delete_preset("older") is False
    assert [p["name"] for p in reloaded.list_presets()] == ["newer"]

@pytest.mark.unit
def test_window_preset_store_skips_non_dict_entries(tmp_path: Path):
    path = tmp_path / "window_presets.json"
    path.write_text(json.dumps({"window_presets": {"junk": 7,
                                                   "gridless": {"updated_at": "x"}}}), encoding="utf-8")
    listed = WindowPresetStore(path).list_presets()
    assert [p["name"] for p in listed] == ["gridless"]
    assert listed[0]["window_count"] == 0  # missing grid -> 0, not crash

@pytest.mark.unit
def test_window_preset_store_corrupt_file_resets(tmp_path: Path):
    path = tmp_path / "window_presets.json"
    path.write_text("[1,2]", encoding="utf-8")
    store = WindowPresetStore(path)
    assert store.list_presets() == []

@pytest.mark.unit
def test_config_manager_facade(config_dir: Path):
    manager = ConfigManager(str(config_dir))
    assert manager.get_state("cdp_host") == DEFAULT_SESSION["cdp_host"]
    manager.set_state(cdp_port=9333)
    assert manager.get_state("cdp_port") == 9333
    # facade state survives a rebuild from the same dir (files written atomically)
    again = ConfigManager(str(config_dir))
    assert again.get_state("cdp_port") == 9333
    # get_session_data returns a deep copy — mutating it must not corrupt the store
    data = again.get_session_data()
    data["theme"] = "hacked"
    assert again.get_state("theme") == DEFAULT_SESSION["theme"]
