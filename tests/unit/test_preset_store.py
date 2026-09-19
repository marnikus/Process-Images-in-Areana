"""Unit tests for PresetStore — the named-preset JSON store (B7 coverage).

RULE 8: each test fails if the store's contract breaks (dedup, deep copy,
persistence round-trip, corrupt-file fallback to defaults).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.persistence.preset_store import DEFAULTS, PresetStore


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "presets.json"


def _write_raw(path: Path, payload) -> None:
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


@pytest.mark.unit
def test_fresh_file_gets_every_default_family(store_path: Path):
    store = PresetStore(store_path)
    for key, value in DEFAULTS.items():
        assert store.all_data()[key] == value


@pytest.mark.unit
def test_corrupt_file_falls_back_to_defaults(store_path: Path):
    _write_raw(store_path, "{broken json")
    store = PresetStore(store_path)
    assert store.all_data() == DEFAULTS


@pytest.mark.unit
def test_non_dict_file_falls_back_to_defaults(store_path: Path):
    _write_raw(store_path, "[1, 2]")
    store = PresetStore(store_path)
    assert store.all_data() == DEFAULTS


@pytest.mark.unit
def test_url_presets_add_dedup_remove_persist(store_path: Path):
    store = PresetStore(store_path)
    assert store.add_url_preset("  https://arena.ai  ") is True   # stripped
    assert store.add_url_preset("https://arena.ai") is False      # dedup
    assert store.add_url_preset("") is False                       # empty refused
    assert PresetStore(store_path).all_data()["url_presets"] == ["https://arena.ai"]
    assert store.remove_url_preset("https://arena.ai") is True
    assert store.remove_url_preset("https://arena.ai") is False
    assert PresetStore(store_path).all_data()["url_presets"] == []


@pytest.mark.unit
def test_prompt_presets_round_trip_and_delete(store_path: Path):
    store = PresetStore(store_path)
    store.save_prompt_preset("daily", "make it [JOB-ID] blue")
    store.save_prompt_preset("daily", "overwritten")
    reloaded = PresetStore(store_path)
    assert reloaded.list_prompt_presets() == ["daily"]
    detailed = reloaded.list_prompt_presets_detailed()
    assert detailed == [{"name": "daily", "template": "overwritten"}]
    assert reloaded.load_prompt_preset("daily") == {"template": "overwritten"}
    assert reloaded.load_prompt_preset("missing") is None
    assert reloaded.delete_prompt_preset("daily") is True
    assert reloaded.delete_prompt_preset("daily") is False
    assert reloaded.list_prompt_presets() == []


@pytest.mark.unit
def test_prompt_load_returns_deep_copy(store_path: Path):
    store = PresetStore(store_path)
    store.save_prompt_preset("p", "make it blue")
    got = store.load_prompt_preset("p")
    got["template"] = "hacked"
    assert store.load_prompt_preset("p") == {"template": "make it blue"}


@pytest.mark.unit
def test_settings_presets_round_trip(store_path: Path):
    store = PresetStore(store_path)
    store.save_settings_preset("fast", {"cooldown_min_seconds": 5})
    reloaded = PresetStore(store_path)
    assert reloaded.list_settings_presets() == ["fast"]
    assert reloaded.load_settings_preset("fast") == {"cooldown_min_seconds": 5}
    assert reloaded.load_settings_preset("nope") is None
    assert reloaded.delete_settings_preset("fast") is True
    assert reloaded.delete_settings_preset("fast") is False


@pytest.mark.unit
def test_arena_presets_list_sorted_by_updated_at_desc(store_path: Path):
    store = PresetStore(store_path)
    store.save_arena_preset("old", {"updated_at": "2026-01-01", "urls": ["u"], "images": []})
    store.save_arena_preset("new", {"updated_at": "2026-02-01", "urls": [], "images": ["i1", "i2"]})
    reloaded = PresetStore(store_path)
    assert reloaded.list_arena_presets() == ["new", "old"]
    detailed = reloaded.list_arena_presets_detailed()
    assert detailed[0] == {"name": "new", "url_count": 0, "image_count": 2,
                           "updated_at": "2026-02-01"}
    assert reloaded.load_arena_preset("old")["updated_at"] == "2026-01-01"
    assert reloaded.load_arena_preset("missing") is None
    assert reloaded.delete_arena_preset("old") is True
    assert reloaded.list_arena_presets() == ["new"]


@pytest.mark.unit
def test_arena_detailed_skips_non_dict_docs(store_path: Path):
    _write_raw(store_path, {"arena_presets": {"junk": "not-a-doc",
                                              "ok": {"updated_at": "x", "urls": [], "images": []}}})
    detailed = PresetStore(store_path).list_arena_presets_detailed()
    assert [d["name"] for d in detailed] == ["ok"]


@pytest.mark.unit
def test_missing_keys_refilled_on_load(store_path: Path):
    _write_raw(store_path, {"url_presets": ["https://only.example"]})
    data = PresetStore(store_path).all_data()
    assert data["url_presets"] == ["https://only.example"]
    assert data["prompt_presets"] == {}
    assert data["settings_presets"] == {}
    assert data["arena_presets"] == {}
