"""WindowPresetStore heals a presets file without a usable `window_presets` map (RULE 13)."""

import json

import pytest

from app.persistence.config_manager import DEFAULT_SESSION, WindowPresetStore

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("stored", [{"window_presets": ["not", "a", "map"]}, {"other": 1}])
def test_init_heals_a_broken_presets_map(tmp_path, stored):
    path = tmp_path / "window_presets.json"
    path.write_text(json.dumps(stored), encoding="utf-8")
    assert WindowPresetStore(path)._data["window_presets"] == {}


def test_load_heals_a_file_that_lost_its_presets_key(tmp_path):
    path = tmp_path / "window_presets.json"
    store = WindowPresetStore(path)
    path.write_text(json.dumps({"other": 1}), encoding="utf-8")
    store.load()
    assert store._data["window_presets"] == {}


def test_firefox_window_defaults_carry_the_task_window_controls():
    """Owner 2026-09-26: captcha solve time 50 s, stacked Ui.Vision window off."""
    ff = DEFAULT_SESSION["firefox_auto"]
    assert ff["captcha_solve_sec"] == 50 and ff["stack_uivision"] is False
