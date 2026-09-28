"""2026-09-28 owner spec "DUPLICATE COOLDOWN CONTROLS" — the pause / captcha values have one
editing home (the URL List bar) and one stored state (session `cooldown_*`). These tests pin
that the values survive a restart, older session files and presets, and that the Settings
"Enable minimum pause" view changes only `enabled` (design:
docs/archive/2026-09-28-cooldown-single-home)."""
from __future__ import annotations

import json

import pytest

from app.browser.page_pool import PagePool
from app.persistence.config_manager import ConfigManager
from app.ui.panels.app_settings import build_cooldown_snapshot, restore_preset_cooldown
from app.ui.panels.page_pool import PagePoolMixin
from tests.test_panel_slots import RecordingSignal, make_host

BAR = {"enabled": True, "min_seconds": 420, "captcha_penalty_seconds": 1320, "rate_limit_penalty_seconds": 2400}


def _host(cfg):
    host, _ = make_host((PagePoolMixin,), _page_pool=PagePool(), config=cfg, _log=lambda m, l="info": None,
                        _emit_pool_status=lambda: None, _persist_cooldowns=lambda: None)
    return host


def _shown(cfg) -> dict:
    """What both views (URL List bar, Settings checkbox) load: get_cooldown_config."""
    return json.loads(_host(cfg).get_cooldown_config())["config"]


def _values(c: dict) -> tuple:
    return c["enabled"], c["min_seconds"], c["captcha_penalty_seconds"], c["rate_limit_penalty_seconds"]


@pytest.fixture
def cfg(isolated_config_dir):
    return ConfigManager(str(isolated_config_dir))


def test_url_list_values_survive_a_restart(isolated_config_dir, cfg):
    _host(cfg).set_cooldown_config(json.dumps(BAR))
    reopened = ConfigManager(str(isolated_config_dir))
    assert _values(_shown(reopened)) == (True, 420, 1320, 2400)


def test_an_older_session_file_loads_with_its_values(isolated_config_dir, cfg):
    """A session written before the Job Cycle box existed (no new-tab keys) keeps its values."""
    cfg.set_state(cooldown_enabled=False, cooldown_min_seconds=600, cooldown_captcha_penalty_seconds=1800)
    reopened = ConfigManager(str(isolated_config_dir))
    reply = json.loads(_host(reopened).get_cooldown_config())
    assert _values(reply["config"]) == (False, 600, 1800, 1800)
    assert reply["new_tab"]["enabled"] is False


def test_settings_enable_view_changes_only_enabled(cfg):
    host = _host(cfg)
    host.set_cooldown_config(json.dumps(BAR))
    host.set_cooldown_config(json.dumps({"enabled": False, "new_tab": False, "new_tab_url": ""}))
    assert _values(_shown(cfg)) == (False, 420, 1320, 2400)


def test_a_preset_restores_the_values_the_url_list_shows(cfg):
    _host(cfg).set_cooldown_config(json.dumps(BAR))
    doc = {"cooldown": build_cooldown_snapshot(cfg)}
    _host(cfg).set_cooldown_config(json.dumps({"enabled": False, "min_seconds": 60, "captcha_penalty_seconds": 60}))
    bridge = type("B", (), {"config": cfg, "_log": lambda self, m, l="info": None})()
    restore_preset_cooldown(bridge, doc)
    assert _values(_shown(cfg)) == (True, 420, 1320, 2400)


def test_an_older_preset_keeps_its_saved_values(cfg):
    """Presets saved before the rate-limit key existed restore their pause / captcha as saved."""
    bridge = type("B", (), {"config": cfg, "_log": lambda self, m, l="info": None})()
    restore_preset_cooldown(bridge, {"cooldown": {"enabled": True, "min_seconds": 480, "captcha_penalty_seconds": 1200}})
    assert _values(_shown(cfg)) == (True, 480, 1200, 1800)


def test_a_preset_without_a_cooldown_block_leaves_the_values_alone(cfg):
    _host(cfg).set_cooldown_config(json.dumps(BAR))
    bridge = type("B", (), {"config": cfg, "_log": lambda self, m, l="info": None})()
    restore_preset_cooldown(bridge, {"name": "old"})
    assert _values(_shown(cfg)) == (True, 420, 1320, 2400)


def _preset_bridge(cfg):
    """What restore_preset_cooldown sees of the bridge: config, log, the slot and the push."""
    host = _host(cfg)
    host.cooldown_config_updated = RecordingSignal()
    return host


def test_a_save_pushes_the_stored_state_to_every_view(cfg):
    """Both views (URL List bar, Settings switch) re-render from the push — no stale "on" box."""
    host = _host(cfg)
    reply = host.set_cooldown_config(json.dumps({"enabled": False}))
    assert host.cooldown_config_updated.emitted == [(reply,)]
    assert json.loads(reply)["config"]["enabled"] is False


def test_a_failed_save_pushes_nothing(cfg):
    host = _host(cfg)
    assert json.loads(host.set_cooldown_config("{not json"))["ok"] is False
    assert host.cooldown_config_updated.emitted == []


def test_a_preset_restore_pushes_the_restored_values(cfg):
    bridge = _preset_bridge(cfg)
    restore_preset_cooldown(bridge, {"cooldown": dict(BAR)})
    (pushed,), = bridge.cooldown_config_updated.emitted
    assert _values(json.loads(pushed)["config"]) == (True, 420, 1320, 2400)


def test_a_preset_without_cooldown_pushes_nothing(cfg):
    bridge = _preset_bridge(cfg)
    restore_preset_cooldown(bridge, {"name": "old"})
    assert bridge.cooldown_config_updated.emitted == []
