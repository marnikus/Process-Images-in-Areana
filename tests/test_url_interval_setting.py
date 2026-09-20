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
