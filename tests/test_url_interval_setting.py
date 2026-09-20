"""S6: the reconcile interval setting — default, clamp, save, publish, wake, no slot."""

import json

import pytest

from app.persistence.config_manager import DEFAULT_SESSION, ConfigManager
from app.services.live.debug_view import cadence, clamp_interval_ms, interval_ms
from app.services.live.bus import live_bus
from tests.characterization.harness import build_bridge, build_stack


@pytest.mark.unit
def test_default_is_5000(tmp_path):
    assert DEFAULT_SESSION["url_reconcile_interval_ms"] == 5000
    cfg = ConfigManager(str(tmp_path / "fresh"))
    assert cfg.get_state("url_reconcile_interval_ms") == 5000


@pytest.mark.unit
@pytest.mark.parametrize("value,want", [
    (1, 500), (60001, 60000), ("abc", 5000), (None, 5000), ("2500", 2500),
    (500, 500), (60000, 60000), (0, 500), (2500.7, 2500),
])
def test_clamp_bounds_are_500_and_60000(value, want):
    assert clamp_interval_ms(value) == want


@pytest.mark.unit
def test_save_settings_persists_only_when_the_key_is_present(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=0)
    bridge = env.bridge
    assert json.loads(bridge.save_settings("{}"))["ok"] is True
    assert bridge.config.get_state("url_reconcile_interval_ms") == 5000
    assert json.loads(bridge.save_settings('{"url_reconcile_interval_ms": 1200}'))["ok"] is True
    assert bridge.config.get_state("url_reconcile_interval_ms") == 1200
    assert interval_ms(bridge) == 1200
    lines = [m for m, _ in env.recs["arena_log"].calls if "url_reconcile_interval_ms" in m or "reconcile interval" in m]
    assert len(lines) == 1


@pytest.mark.unit
def test_the_value_is_published_in_progress_updated(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=0)
    bridge = env.bridge
    bridge.config.set_state(url_reconcile_interval_ms=1200)
    bridge._emit_arena_state()
    payload = json.loads(env.recs["progress_updated"].calls[-1][0])
    assert payload["live"]["url_interval_ms"] == 1200
    assert cadence(bridge)["url_interval_ms"] == 1200


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_setting_wakes_the_loop(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=0)
    bridge = env.bridge
    bridge.save_settings('{"url_reconcile_interval_ms": 1200}')
    assert await live_bus(bridge).wait(0.05) == "interval"


@pytest.mark.unit
def test_no_new_slot_and_no_new_signal():
    from pathlib import Path
    from tests.test_bridge_slots import test_frozen_slot_surface_exact, test_panel_packing
    test_frozen_slot_surface_exact()
    test_panel_packing()
    src = Path("app/ui/panels/app_settings.py").read_text()
    assert sum(1 for line in src.splitlines() if line.lstrip().startswith("@Slot")) == 10
