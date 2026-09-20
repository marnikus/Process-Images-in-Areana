"""S10 equivalence: real settings slot, persistence, progress and wake boundary."""
import json

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.live.bus import live_bus
from app.services.live.debug_view import clamp_interval_ms
from tests.characterization.harness import build_bridge


def test_default_is_5000(tmp_path):
    assert ConfigManager(tmp_path).get_state('url_reconcile_interval_ms') == 5000


@pytest.mark.parametrize('raw,expected', [(1, 500), (60001, 60000), ('abc', 5000),
                                         (None, 5000), (2500, 2500)])
def test_clamp_bounds_and_invalid_values(raw, expected):
    assert clamp_interval_ms(raw) == expected


def test_real_save_persists_emits_and_wakes_only_when_key_is_present(tmp_path):
    env = build_bridge(tmp_path, [])
    bus = live_bus(env.bridge)
    assert 'interval' not in bus.reasons()
    assert json.loads(env.bridge.save_settings('{"url_reconcile_interval_ms":1}'))['ok']
    assert env.cfg.get_state('url_reconcile_interval_ms') == 500
    assert bus.reasons().count('interval') == 1
    progress = json.loads(env.recs['progress_updated'].calls[-1][0])
    assert progress['live']['url_interval_ms'] == 500
    assert json.loads(env.bridge.save_settings('{"max_retries":4}'))['ok']
    assert env.cfg.get_state('url_reconcile_interval_ms') == 500
    assert bus.reasons().count('interval') == 1
    assert json.loads(env.bridge.save_settings('{"url_reconcile_interval_ms":"bad"}'))['ok']
    assert env.cfg.get_state('url_reconcile_interval_ms') == 5000
    assert bus.reasons().count('interval') == 2


def test_interval_first_edit_undo_redo_uses_existing_global_settings_history(tmp_path):
    env = build_bridge(tmp_path, [])
    env.bridge.undo_service.set_history([], -1)
    env.cfg.set_state(url_reconcile_interval_ms=7000)
    assert json.loads(env.bridge.save_settings('{"url_reconcile_interval_ms":9000}'))['ok']
    assert env.cfg.get_state('url_reconcile_interval_ms') == 9000
    undone = json.loads(env.bridge.undo())
    assert undone['kind'] == 'settings'
    assert env.cfg.get_state('url_reconcile_interval_ms') == 7000
    progress = json.loads(env.recs['progress_updated'].calls[-1][0])
    assert progress['live']['url_interval_ms'] == 7000
    assert json.loads(env.bridge.redo())['kind'] == 'settings'
    assert env.cfg.get_state('url_reconcile_interval_ms') == 9000
    assert live_bus(env.bridge).reasons().count('interval') == 3
    history, _ = env.bridge.undo_service.history()
    assert [entry['kind'] for entry in history] == ['settings', 'settings']


def test_history_remember_restores_interval_but_old_settings_entry_leaves_it_alone(tmp_path):
    from app.ui.services.undo_entries import remember_global_edit, apply_undo_entry
    env = build_bridge(tmp_path, [])
    remember_global_edit(env.bridge, 'settings', {'url_reconcile_interval_ms': 1})
    assert env.cfg.get_state('url_reconcile_interval_ms') == 500
    apply_undo_entry(env.bridge, {'kind':'settings', 'value':{'timeouts':{'page_load':40}}})
    assert env.cfg.get_state('url_reconcile_interval_ms') == 500
