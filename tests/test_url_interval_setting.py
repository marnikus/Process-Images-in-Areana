"""S6 · the reconcile interval is a user setting (D-12R, I-42 → SoR row 8).

One key `url_reconcile_interval_ms` (default 5000, clamped 500…60000 by the
one clamp owner `debug_view.clamp_interval_ms`), written by the existing
`save_settings` slot, read by the loop every pass, published on the pushed
`progress_updated.live` payload (the control's ONLY read path — no new slot,
D-20) and waking the live bus so the next pass uses it immediately.

RED at base: `ModuleNotFoundError: app.services.live.debug_view`.
"""

import json
import re
from pathlib import Path

import pytest

from app.persistence.config_manager import DEFAULT_SESSION, ConfigManager
from app.services.live import debug_view as dv
from app.services.live.bus import live_bus
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit
APP = Path(__file__).resolve().parents[1] / "app"


def test_default_is_5000(tmp_path):
    assert DEFAULT_SESSION["url_reconcile_interval_ms"] == 5000
    cfg = ConfigManager(str(tmp_path / "cfg"))
    assert cfg.get_state("url_reconcile_interval_ms") == 5000


@pytest.mark.parametrize("raw, want", [(1, 500), (60001, 60000), ("abc", 5000), (None, 5000), (2500, 2500), ("1200", 1200)])
def test_clamp_bounds_are_500_and_60000(raw, want):
    assert dv.clamp_interval_ms(raw) == want
    assert (dv.MIN_MS, dv.MAX_MS, dv.DEFAULT_MS) == (500, 60000, 5000)


def test_save_settings_persists_only_when_the_key_is_present(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    bridge = env.bridge
    assert json.loads(bridge.save_settings("{}"))["ok"] is True
    assert dv.interval_ms(bridge) == 5000
    lines_before = len(env.recs["arena_log"].calls)
    assert json.loads(bridge.save_settings(json.dumps({"url_reconcile_interval_ms": 1200})))["ok"] is True
    assert bridge.config.get_state("url_reconcile_interval_ms") == 1200 and dv.interval_ms(bridge) == 1200
    new_lines = [m for m, _l in env.recs["arena_log"].calls[lines_before:] if "reconcile" in m.lower()]
    assert len(new_lines) == 1 and "1200" in new_lines[0]
    assert json.loads(bridge.save_settings(json.dumps({"url_reconcile_interval_ms": 99999})))["ok"] is True
    assert bridge.config.get_state("url_reconcile_interval_ms") == 60000  # clamped on write


def test_the_value_is_published_in_progress_updated(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    env.bridge.config.set_state(url_reconcile_interval_ms=1200)
    env.bridge._emit_arena_state()
    prog = json.loads(env.recs["progress_updated"].calls[-1][0])
    assert prog["live"]["url_interval_ms"] == 1200
    assert set(prog["live"]) == {"url_interval_ms", "last_pass_at", "passes"}
    assert dv.cadence(env.bridge) == prog["live"]


@pytest.mark.asyncio
async def test_the_setting_wakes_the_loop(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    env.bridge.save_settings(json.dumps({"url_reconcile_interval_ms": 900}))
    assert await live_bus(env.bridge).wait(0.05) == "interval"


def test_no_new_slot_and_no_new_signal():
    src = (APP / "ui" / "panels" / "app_settings.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^\s*@Slot\(", src, re.M)) == 10  # D-20: the frozen surface (tests/test_bridge_slots.py: app_settings 10)
    assert "apply_url_interval" in src
