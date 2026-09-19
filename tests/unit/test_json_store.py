"""Unit tests for persistence/json_store.py — the one atomic JSON helper.

RULE 8: each test fails if json_store (or its atomicity/default semantics)
is deleted or inverted. RULE 13/23: corrupt input must fall back, saves
must never leave partial or temp files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.persistence.json_store import load_json, save_json_atomic


@pytest.mark.unit
def test_load_missing_file_returns_deep_copy_of_default(tmp_path: Path):
    got = load_json(tmp_path / "none.json", {"a": {"b": []}})
    assert got == {"a": {"b": []}}
    got["a"]["b"].append(1)
    again = load_json(tmp_path / "none.json", {"a": {"b": []}})
    assert again == {"a": {"b": []}}, "default must never be shared by reference"


@pytest.mark.unit
def test_load_round_trip_after_atomic_save(tmp_path: Path):
    path = tmp_path / "state.json"
    save_json_atomic(path, {"grid": [1, 2], "nested": {"ok": True}})
    assert load_json(path, {}) == {"grid": [1, 2], "nested": {"ok": True}}


@pytest.mark.unit
def test_load_corrupt_json_falls_back_to_default(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not json at all", encoding="utf-8")
    assert load_json(path, {"fallback": True}) == {"fallback": True}


@pytest.mark.unit
def test_load_non_dict_json_falls_back_to_default(tmp_path: Path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_json(path, {"fallback": True}) == {"fallback": True}


@pytest.mark.unit
def test_save_is_atomic_no_tmp_residue_and_valid_json(tmp_path: Path):
    path = tmp_path / "deep" / "out.json"
    save_json_atomic(path, {"x": 1})
    leftovers = [p.name for p in path.parent.iterdir() if p.name != "out.json"]
    assert leftovers == [], f"temp files left behind: {leftovers}"
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": 1}
    # overwriting an existing file replaces it atomically
    save_json_atomic(path, {"x": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": 2}
    assert [p.name for p in path.parent.iterdir() if p.name != "out.json"] == []
