"""The URL reconcile interval is a user setting with one owner (S6, D-11 / D-12R).

`url_reconcile_interval_ms` lives in DEFAULT_SESSION (5000), is clamped by
`debug_view.clamp_interval_ms` (500…60000), written only by `save_settings`
(no new slot, D-20), read by the reconcile loop every pass, published on
`progress_updated.live` (the control's only read path) and its change wakes
the reconciler immediately.
"""

import json
from pathlib import Path

import pytest

from app.persistence.config_manager import DEFAULT_SESSION, ConfigManager
from app.services.live import debug_view, reconcile
from app.ui.panels import layout_state
from tests.characterization.harness import build_bridge, build_stack
from tests.characterization.test_batch_goldens import CORE_STACK

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def test_default_is_5000(tmp_path):
    assert DEFAULT_SESSION["url_reconcile_interval_ms"] == 5000
    cfg = ConfigManager(str(tmp_path / "cfg"))
    assert cfg.get_state("url_reconcile_interval_ms") == 5000
    env = build_bridge(tmp_path, build_stack(CORE_STACK))
    assert debug_view.interval_ms(env.bridge) == 5000


@pytest.mark.parametrize("raw,expected", [(1, 500), (60001, 60000), ("abc", 5000), (None, 5000),
                                          (2500, 2500), ("1200", 1200), (-7, 500)])
def test_clamp_bounds_are_500_and_60000(raw, expected):
    assert debug_view.clamp_interval_ms(raw) == expected
    assert (debug_view.MIN_MS, debug_view.MAX_MS, debug_view.DEFAULT_MS) == (500, 60000, 5000)


def test_save_settings_persists_only_when_the_key_is_present(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK))
    bridge = env.bridge
    assert json.loads(bridge.save_settings("{}"))["ok"] is True
    assert bridge.config.get_state("url_reconcile_interval_ms") == 5000
    assert json.loads(bridge.save_settings(json.dumps({"url_reconcile_interval_ms": 1200})))["ok"] is True
    assert bridge.config.get_state("url_reconcile_interval_ms") == 1200
    lines = [m for m, _l in env.recs["arena_log"].calls if "URL reconcile interval" in m]
    assert len(lines) == 1 and "1200" in lines[0]
    bridge.save_settings(json.dumps({"url_reconcile_interval_ms": 99}))    # clamped on write, one owner
    assert bridge.config.get_state("url_reconcile_interval_ms") == 500


def test_the_value_is_published_in_progress_updated(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK))
    env.bridge.save_settings(json.dumps({"url_reconcile_interval_ms": 1200}))
    layout_state.emit_arena_state(env.bridge)
    payload = json.loads(env.recs["progress_updated"].calls[-1][0])
    assert payload["live"]["url_interval_ms"] == 1200
    assert set(payload["live"]) >= {"url_interval_ms", "last_pass_at", "passes"}
    assert payload["run_state"] == "idle"                                  # the existing keys survive


def test_the_setting_wakes_the_reconciler(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK))
    env.bridge.save_settings(json.dumps({"url_reconcile_interval_ms": 700}))
    assert reconcile.url_bus(env.bridge).reasons() == ["interval"]


def test_no_new_slot_and_no_new_signal():
    src = (ROOT / "app/ui/panels/app_settings.py").read_text(encoding="utf-8")
    assert src.count("@Slot(") == 10                                       # D-20: save_settings is the writer
    assert "def apply_url_interval(" in src
