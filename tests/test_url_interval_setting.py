"""S6 url_reconcile_interval_ms — default, clamp, save path, publish + wake (plan §S6 tests 18-23).

RED at base: the config key, `debug_view`, `apply_url_interval` and the `prog["live"]`
publish line do not exist yet.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.live import debug_view
from app.services.live.bus import LiveBus, live_bus
from app.ui import bridge_context
from app.ui.panels import app_settings as apps
from app.ui.panels import layout_state

KEY = "url_reconcile_interval_ms"


def make_bridge(tmp_path):
    b = SimpleNamespace(
        state=SimpleNamespace(settings=SimpleNamespace(timeouts={}, highlight={}),
                              folder={}, urls=[], images=[], prompt={"user_prompt": ""}),
        _log=lambda *a: None,
        config=SimpleNamespace(get_state=lambda k, d=None: tmp_cfg(b).get(k, d),
                               set_state=lambda **kw: tmp_cfg(b).update(kw)),
        _watcher=None,
        _live_bus=LiveBus(),
        _set={},
        undo_service=SimpleNamespace(push=lambda *a: None),
    )
    b._save_arena = lambda: None
    return b


_CFGS = {}


def tmp_cfg(b):
    return _CFGS.setdefault(id(b), {KEY: 700})


@pytest.mark.unit
def test_default_is_5000(tmp_path):
    cfg = ConfigManager(str(tmp_path / "cfg"))
    assert cfg.get_state(KEY) == 5000


@pytest.mark.unit
@pytest.mark.parametrize("value,expected", [
    (1, 500), (499, 500), (60001, 60000), ("abc", 5000), (None, 5000), (2500, 2500),
])
def test_clamp_bounds_are_500_and_60000(value, expected):
    assert debug_view.clamp_interval_ms(value) == expected


@pytest.mark.unit
def test_save_settings_persists_only_when_the_key_is_present(tmp_path):
    b = make_bridge(tmp_path)
    apps.apply_url_interval(b, {})
    assert tmp_cfg(b)[KEY] == 700                                   # absent: untouched
    apps.apply_url_interval(b, {KEY: 1200})
    assert tmp_cfg(b)[KEY] == 1200
    apps.apply_url_interval(b, {KEY: 99999})
    assert tmp_cfg(b)[KEY] == 60000                                 # clamped on write


@pytest.mark.unit
def test_interval_ms_reads_the_config_value(tmp_path):
    b = make_bridge(tmp_path)
    assert debug_view.interval_ms(b) == 700
    assert seconds_of(b) == 0.7


def seconds_of(b):
    return debug_view.interval_ms(b) / 1000.0


@pytest.mark.unit
def test_the_setting_wakes_the_loop(tmp_path):
    b = make_bridge(tmp_path)
    apps.apply_url_interval(b, {KEY: 1200})
    assert "interval" in live_bus(b).reasons()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_value_is_published_in_progress_updated(tmp_path):
    from tests.characterization.harness import build_stack, CORE_STACK, build_bridge
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    env.bridge.config.set_state(**{KEY: 1200})
    env.bridge.progress_updated.calls.clear()
    env.bridge._emit_arena_state()
    payload = json.loads(env.bridge.progress_updated.calls[-1][0])
    assert payload["live"]["url_interval_ms"] == 1200


@pytest.mark.unit
def test_cadence_shape(tmp_path):
    from tests.characterization.harness import build_stack, CORE_STACK, build_bridge
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    env.bridge.config.set_state(**{KEY: 1200})
    env.bridge._last_url_pass = 42.5
    live = debug_view.cadence(env.bridge)
    assert live["url_interval_ms"] == 1200 and live["last_pass_at"] == 42.5
    assert isinstance(live["passes"], int)


@pytest.mark.unit
def test_no_new_slot_is_added():
    src = open("app/ui/panels/app_settings.py", encoding="utf-8").read()
    decl = src.index("def apply_url_interval")
    assert "@Slot" not in src[max(0, decl - 160):decl], "D-20: setting flows through save_settings"
