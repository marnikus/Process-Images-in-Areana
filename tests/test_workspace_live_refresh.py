"""Post-restore LIVE refresh — the 2026-09-25 owner bug report.

Restore used to rewrite the stores behind the live app's back: the Settings
window kept showing the old values (and the next Settings save clobbered the
restore right back), the watcher kept stale timeouts, the page pool kept
stale cooldown timers and re-persisted them over the restored file. These
tests pin the full chain on a real Bridge: state AND live consumers.
"""

import json
import threading

import pytest

from app.persistence.config_manager import ConfigManager
from app.services.workspace import apply as ws_apply
from app.services.workspace import save as ws_save
from app.services.workspace.save import SaveRequest
from app.ui.bridge import Bridge

pytestmark = pytest.mark.unit


@pytest.fixture()
def bridge(tmp_path):
    return Bridge(config_manager=ConfigManager(config_dir=str(tmp_path)),
                  state_path=tmp_path / "app_state.json")


def _save(bridge, name="checkpoint") -> str:
    reply = ws_save.save_workspace(bridge, SaveRequest(name=name))
    assert reply["ok"], reply
    return reply["path"]


def _settings_save(bridge, generation, interval=5000) -> None:
    """The REAL user path — the Settings window's save_settings slot."""
    payload = {"generation_timeout": generation, "timeout_seconds": generation,
               "url_reconcile_interval_ms": interval}
    result = json.loads(bridge.save_settings(json.dumps(payload)))
    assert result["ok"], result


def _restore(bridge, snapshot) -> dict:
    reply = json.loads(bridge.restore_workspace(str(snapshot), "{}"))
    assert reply["ok"], reply
    return reply


def test_restore_rewrites_settings_changed_after_the_checkpoint(bridge):
    _settings_save(bridge, generation=111, interval=5000)
    snapshot = _save(bridge)
    _settings_save(bridge, generation=999, interval=6000)  # user changes settings
    assert bridge.state.settings.timeouts["generation"] == 999
    _restore(bridge, snapshot)
    # the live state is back (not just the file)...
    assert bridge.state.settings.timeouts["generation"] == 111
    # ...and the session key too (session.json reloaded into the store)
    assert bridge.config.get_state("url_reconcile_interval_ms") == 5000
    # ...and the payload the UI panels render from carries it (get_arena_state
    # is the slot the Settings window's values come from)
    live = json.loads(bridge.get_arena_state())
    assert live["settings"]["timeouts"]["generation"] == 111


class _SpySignal:
    """Instance-level signal stand-in (the headless qt_compat Signal is a no-op)."""

    def __init__(self):
        self.payloads = []

    def emit(self, *payload) -> None:
        self.payloads.extend(payload)


def test_restore_emits_arena_state_updated(bridge):
    bridge.state.prompt["user_prompt"] = "checkpoint prompt"
    snapshot = _save(bridge)
    bridge.state.prompt["user_prompt"] = "changed"
    spy = _SpySignal()
    bridge.arena_state_updated = spy
    _restore(bridge, snapshot)
    assert spy.payloads, "restore must emit arena_state_updated (the UI refresh signal)"
    payload = json.loads(spy.payloads[-1])
    assert payload["prompt"]["template"] == "checkpoint prompt"


def test_restore_refreshes_undo_history_and_window_preset_lists(bridge):
    snapshot = _save(bridge)
    undo_spy, history_spy, presets_spy = _SpySignal(), _SpySignal(), _SpySignal()
    bridge.undo_state_changed = undo_spy
    bridge.job_history_updated = history_spy
    bridge.window_preset_list_updated = presets_spy
    _restore(bridge, snapshot)
    assert undo_spy.payloads, "undo timeline must be re-pushed"
    assert history_spy.payloads, "job history must be re-pushed"
    assert presets_spy.payloads, "window preset list must be re-pushed"


class _FakeWatcher:
    """Records update_config calls (the live watcher keeps its own config copy)."""

    def __init__(self):
        class _Config:
            check_interval_ms = 1
            captcha_timeout_sec = 2
            generation_timeout_sec = 3
            enabled = False
        self.config = _Config()
        self.updates = []

    def update_config(self, **kwargs):
        self.updates.append(kwargs)
        for key, value in kwargs.items():
            setattr(self.config, key, value)


def test_session_restore_reapplies_watcher_config(bridge):
    bridge._watcher = _FakeWatcher()
    bridge.config.set_state(watcher_generation_timeout_sec=555,
                            watcher_captcha_timeout_sec=42)
    snapshot = _save(bridge)
    bridge.config.set_state(watcher_generation_timeout_sec=999)
    watcher = bridge._watcher
    watcher.updates.clear()
    reply = _restore(bridge, snapshot)
    assert "session_settings" in reply["restored"]
    assert any(u.get("generation_timeout_sec") == 555 for u in watcher.updates)
    assert watcher.config.generation_timeout_sec == 555
    assert any("watcher config re-applied" in note for note in reply["reconciled"])


def test_cooldown_restore_reapplies_into_the_live_pool(bridge, monkeypatch):
    from app.services.workspace.providers import cooldowns as cd
    calls = {"timers": [], "counters": []}
    monkeypatch.setattr(cd, "load_entries",
                        lambda path: {"tab-1": {"cooldown_until": 123.0}})
    monkeypatch.setattr(cd, "load_stats", lambda path: {"http://x": {"jobs_completed": 3}})
    monkeypatch.setattr(cd, "restore_cooldown_entry",
                        lambda pool, tab_id, entry: calls["timers"].append(tab_id) or True)
    monkeypatch.setattr(cd, "restore_page_stats",
                        lambda pool, tab_id, url, row: calls["counters"].append(url) or 5)

    class _Page:
        url = "http://x"

    class _Pool:
        _pages = {"tab-1": _Page()}
        _lock = threading.Lock()

    bridge._page_pool = _Pool()
    snapshot = _save(bridge)
    calls["timers"].clear()
    calls["counters"].clear()
    reply = _restore(bridge, snapshot)
    assert "cooldowns" in reply["restored"]
    assert calls["timers"] == ["tab-1"]          # the stale pool timer is replaced
    assert calls["counters"] == ["http://x"]     # the restored counter is re-applied
    assert any("re-applied 1 timer" in note for note in reply["reconciled"])


def test_failed_restore_does_not_touch_the_live_consumers(bridge, tmp_path):
    reply = json.loads(bridge.restore_workspace(str(tmp_path), "{}"))
    assert reply["ok"] is False
    assert reply.get("reconciled") is None
    assert ws_apply is not None  # import guard: the module stayed loadable
