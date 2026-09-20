"""app_settings apply helpers — the module functions `save_settings` delegates to.

Pure state/config writers with clamps; each is exercised directly so a
deleted clamp or a dropped config sync fails here (RULE 8).
"""

from types import SimpleNamespace

import pytest

from app.ui.panels import app_settings as aps

pytestmark = pytest.mark.unit


class Watcher:
    def __init__(self):
        self.updates = []

    def update_config(self, **kw):
        self.updates.append(kw)


def make_bridge(watcher=None):
    logs, cfg = [], {}
    state = SimpleNamespace(settings=SimpleNamespace(timeouts={}, highlight={}, supported_types=[]),
                            folder={})
    return SimpleNamespace(state=state, _watcher=watcher, _logs=logs, _cfg=cfg,
                           _log=lambda m, l="info": logs.append((m, l)),
                           config=SimpleNamespace(set_state=lambda **kw: cfg.update(kw)))


def test_generation_timeout_is_clamped_and_synced_to_the_watcher():
    bridge = make_bridge(Watcher())
    aps.apply_generation_timeout(bridge, {})                       # absent key: no-op
    assert bridge.state.settings.timeouts == {} and bridge._cfg == {}
    aps.apply_generation_timeout(bridge, {"generation_timeout": 5})
    assert bridge.state.settings.timeouts["generation"] == 30      # floor
    aps.apply_generation_timeout(bridge, {"generation_timeout": 99999})
    assert bridge.state.settings.timeouts["generation"] == 3600    # ceiling
    assert bridge._cfg["watcher_generation_timeout_sec"] == 3600
    assert bridge._watcher.updates[-1] == {"generation_timeout_sec": 3600}
    assert any("Generation timeout set to 3600s" in m for m, _ in bridge._logs)


def test_watcher_timeouts_each_clamp_and_log():
    bridge = make_bridge(Watcher())
    aps.apply_watcher_timeouts(bridge, {"watcher_captcha_timeout_sec": 1,
                                        "watcher_generation_timeout_sec": "bogus"})
    assert bridge._cfg == {"watcher_captcha_timeout_sec": 10}      # the bogus one is skipped, not fatal
    assert bridge._watcher.updates == [{"captcha_timeout_sec": 10}]
    assert any("Watcher captcha timeout set to 10s" in m for m, _ in bridge._logs)
    no_watcher = make_bridge(None)
    aps.apply_watcher_timeouts(no_watcher, {"watcher_generation_timeout_sec": 4000})
    assert no_watcher._cfg == {"watcher_generation_timeout_sec": 3600}


def test_supported_types_land_on_folder_and_settings():
    state = make_bridge().state
    aps.apply_supported_types(state, {})
    assert state.folder == {} and state.settings.supported_types == []
    aps.apply_supported_types(state, {"supported_types": [".png"]})
    assert state.folder["supported_types"] == [".png"] and state.settings.supported_types == [".png"]


def test_highlight_duration_lands_on_settings_and_config():
    bridge = make_bridge()
    aps.apply_highlight_duration(bridge.state, bridge.config, {"highlight_duration": "3"})
    assert bridge.state.settings.highlight["duration_seconds"] == 3
    assert bridge._cfg == {"highlight_duration": 3}
