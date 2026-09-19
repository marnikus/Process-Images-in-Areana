"""json_store — canonical atomic JSON writer + corrupt-tolerant loader (RULE 13).

Every store (config, presets, undo, state, captcha key, cooldown) now shares
this module; these tests pin its contract directly (RULE 8): atomic replace,
byte format, 0600 mode for credentials, and missing/corrupt/wrong-type loads
return a fresh deep copy of the default — never a crash, never a shared
mutable default.
"""
import json
import os
import stat
import tempfile
from pathlib import Path

import pytest

from app.persistence.json_store import atomic_write_json, load_json

DEFAULT = {"a": 1, "nested": {"b": [1, 2]}}


@pytest.mark.unit
def test_atomic_write_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.json"
        atomic_write_json(path, DEFAULT)
        assert json.loads(path.read_text(encoding="utf-8")) == DEFAULT


@pytest.mark.unit
def test_atomic_write_format_indent2_non_ascii():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.json"
        atomic_write_json(path, {"label": "český"})
        text = path.read_text(encoding="utf-8")
        assert text == json.dumps({"label": "český"}, indent=2, ensure_ascii=False)


@pytest.mark.unit
def test_atomic_write_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "deep" / "nest" / "data.json"
        atomic_write_json(path, {"ok": True})
        assert path.exists()


@pytest.mark.unit
def test_atomic_write_mode_0600():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "key.json"
        atomic_write_json(path, {"key": "x"}, mode=0o600)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


@pytest.mark.unit
def test_atomic_write_leaves_no_temp_files():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.json"
        atomic_write_json(path, DEFAULT)
        atomic_write_json(path, DEFAULT)  # overwrite
        assert sorted(p.name for p in Path(tmp).iterdir()) == ["data.json"]


@pytest.mark.unit
def test_load_missing_returns_default():
    with tempfile.TemporaryDirectory() as tmp:
        missing = DEFAULT
        got = load_json(Path(tmp) / "nope.json", missing)
        assert got == DEFAULT
        got["a"] = 99  # mutating the result must not leak into the default
        assert missing["a"] == 1


@pytest.mark.unit
def test_load_garbage_returns_default():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        assert load_json(path, DEFAULT) == DEFAULT


@pytest.mark.unit
def test_load_wrong_type_returns_default():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "list.json"
        path.write_text("[1, 2]", encoding="utf-8")
        assert load_json(path, DEFAULT) == DEFAULT  # expect_type=dict by default
        assert load_json(path, [0], expect_type=list) == [1, 2]


@pytest.mark.unit
def test_load_valid_returns_data_not_default_copy():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ok.json"
        atomic_write_json(path, {"a": 42})
        assert load_json(path, DEFAULT) == {"a": 42}
