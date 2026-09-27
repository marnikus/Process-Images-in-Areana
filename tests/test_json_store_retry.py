"""json_store: bounded replace retry (B10) + wholesale store replacement validation.

The retry came in with the Global Saving System merge; these pin its contract:
transient sharing violations retry with backoff, anything else raises at once,
the last attempt's error reaches the caller, and no temp file is left behind.
"""

from __future__ import annotations

import errno
from pathlib import Path

import pytest

from app.persistence import json_store
from app.persistence.config_manager import WindowPresetStore
from app.persistence.preset_store import PresetStore


@pytest.fixture
def sleeps(monkeypatch):
    calls: list = []
    monkeypatch.setattr(json_store.time, "sleep", calls.append)
    return calls


def _flaky_replace(monkeypatch, failures: list):
    """Path.replace raising the queued errors first, then the real replace."""
    real = Path.replace
    attempts = {"n": 0}

    def fake(self, target):
        attempts["n"] += 1
        if failures:
            raise failures.pop(0)
        return real(self, target)

    monkeypatch.setattr(Path, "replace", fake)
    return attempts


def _leftovers(folder: Path) -> list:
    return [p.name for p in folder.iterdir() if p.name.endswith(".tmp")]


def test_transient_errors_retry_with_doubling_backoff(tmp_path, monkeypatch, sleeps):
    target = tmp_path / "cooldowns.json"
    attempts = _flaky_replace(monkeypatch, [PermissionError("held"),
                                            OSError(errno.EBUSY, "busy")])
    json_store.save_json_atomic(target, {"a": 1})
    assert json_store.load_json(target, {}) == {"a": 1}
    assert attempts["n"] == 3
    assert sleeps == [0.02, 0.04]
    assert _leftovers(tmp_path) == []


def test_non_transient_error_raises_without_retry(tmp_path, monkeypatch, sleeps):
    attempts = _flaky_replace(monkeypatch, [OSError(errno.ENOSPC, "disk full")])
    with pytest.raises(OSError) as info:
        json_store.save_json_atomic(tmp_path / "s.json", {"a": 1})
    assert info.value.errno == errno.ENOSPC
    assert attempts["n"] == 1 and sleeps == []
    assert _leftovers(tmp_path) == []


def test_persistent_sharing_violation_gives_up_after_five(tmp_path, monkeypatch, sleeps):
    attempts = _flaky_replace(monkeypatch, [PermissionError("held")] * 5)
    with pytest.raises(PermissionError):
        json_store.save_json_atomic(tmp_path / "s.json", {"a": 1})
    assert attempts["n"] == 5
    assert sleeps == [0.02, 0.04, 0.08, 0.16]
    assert _leftovers(tmp_path) == []


def test_is_transient_classification():
    assert json_store._is_transient(PermissionError("x"))
    assert json_store._is_transient(OSError(errno.EACCES, "x"))
    assert not json_store._is_transient(OSError(errno.ENOENT, "x"))


@pytest.mark.parametrize("bad", ["nope", {"url_presets": {}}, {"prompt_presets": []}])
def test_preset_store_replace_all_refuses_wrong_shapes(tmp_path, bad):
    store = PresetStore(tmp_path / "arena_presets.json")
    before = store.all_data()
    with pytest.raises(ValueError):
        store.replace_all(bad)
    assert store.all_data() == before


def test_preset_store_replace_all_persists_valid_doc(tmp_path):
    path = tmp_path / "arena_presets.json"
    doc = PresetStore(path).all_data()
    doc["prompt_presets"] = {"p": "hello"}
    assert PresetStore(path).replace_all(doc) is True
    assert PresetStore(path).all_data()["prompt_presets"] == {"p": "hello"}


@pytest.mark.parametrize("bad", [[], {}, {"window_presets": []}])
def test_window_preset_store_replace_all_refuses_wrong_shapes(tmp_path, bad):
    store = WindowPresetStore(tmp_path / "window_presets.json")
    with pytest.raises(ValueError):
        store.replace_all(bad)


def test_window_preset_store_round_trip(tmp_path):
    path = tmp_path / "window_presets.json"
    assert WindowPresetStore(path).replace_all({"window_presets": {"a": {"v": 8}}})
    assert WindowPresetStore(path).all_data() == {"window_presets": {"a": {"v": 8}}}


def test_helpers_one_try_each(tmp_path, sleeps):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("{}")
    assert json_store._try_replace(src, dst) is True and dst.exists()
    assert json_store._transient_or_raise(PermissionError("held")) is False
    with pytest.raises(FileNotFoundError):
        json_store._transient_or_raise(FileNotFoundError(errno.ENOENT, "gone"))
    assert json_store._attempt(lambda: True, 9.0) is True and sleeps == []
    assert json_store._attempt(lambda: False, 0.5) is False and sleeps == [0.5]


def test_preset_shape_error_names_the_bad_section():
    from app.persistence.preset_store import DEFAULTS, shape_error
    good = {k: type(v)() for k, v in DEFAULTS.items()}
    assert shape_error(good) is None
    assert shape_error([]) == "preset store needs an object"
    assert "'url_presets'" in shape_error({**good, "url_presets": {}})
