"""app_settings module-level appliers — direct covers (RULE 16 coverage ratchet).

The import/export slots exercise these through dialogs; here the pure helpers
get their own deterministic pins so the file floor holds without dialog
machinery (RULE 8: the real functions, controllable doubles).
"""

from types import SimpleNamespace

from app.ui.panels import app_settings as apps


def state_wiring():
    return SimpleNamespace(
        settings=SimpleNamespace(timeouts={}, folder_types=None, highlight={},
                                 supported_types=None, cooldown={}),
        folder={}, urls=[], images=[],
    )


def bridge_wiring(**over):
    b = SimpleNamespace(state=state_wiring(), _log=lambda *a: None,
                        config=SimpleNamespace(set_state=lambda **_k: b._set.update(_k)),
                        _watcher=None, _set={}, undo_service=SimpleNamespace(push=lambda *a: None))
    for k, v in over.items():
        setattr(b, k, v)
    return b


def test_apply_simple_key_coerces_into_the_named_section():
    st = state_wiring()
    st.settings.timeouts["download"] = 0
    apps.apply_simple_key(st, {"download_timeout": "120"}, ("download_timeout", "timeouts", "download", int))
    assert st.settings.timeouts["download"] == 120
    apps.apply_simple_key(st, {}, ("download_timeout", "timeouts", "download", int))
    assert st.settings.timeouts["download"] == 120      # absent key: untouched


def test_apply_generation_timeout_clamps_and_reports():
    b = bridge_wiring()
    apps.apply_generation_timeout(b, {"generation_timeout": "9000"})
    assert b.state.settings.timeouts["generation"] == 3600     # clamped to ceiling
    apps.apply_generation_timeout(b, {"generation_timeout": 5})
    assert b.state.settings.timeouts["generation"] == 30       # clamped to floor
    apps.apply_generation_timeout(b, {})                       # absent: untouched
    assert b.state.settings.timeouts["generation"] == 30


def test_apply_supported_types_and_highlight_duration():
    st = state_wiring()
    b = bridge_wiring()
    apps.apply_supported_types(st, {"supported_types": ["png"]})
    assert st.folder["supported_types"] == ["png"] and st.settings.supported_types == ["png"]
    apps.apply_supported_types(st, {})                          # absent: untouched
    apps.apply_highlight_duration(st, b.config, {"highlight_duration": "2"})
    assert st.settings.highlight["duration_seconds"] == 2
    apps.apply_highlight_duration(st, b.config, {})


def test_apply_watcher_timeouts_clamps_and_updates_watcher():
    updated = {}
    watcher = SimpleNamespace(update_config=lambda **kw: updated.update(kw))
    b = bridge_wiring(_watcher=watcher)
    key, lo, update_kw, _label = apps._WATCHER_TIMEOUTS[0]
    apps.apply_watcher_timeouts(b, {key: "99999"})
    assert b._set[key] == 3600 and updated[update_kw] == 3600   # clamped, watcher told
    apps.apply_watcher_timeouts(b, {})                          # absent key: no call
    assert list(updated) == [update_kw]


def test_undo_push_helpers_are_best_effort(monkeypatch):
    monkeypatch.setattr(apps.arena_serialize, "arena_to_js", lambda state: {"settings": {}})
    pushed = []
    b = bridge_wiring()
    b.undo_service = SimpleNamespace(push=lambda kind, js: pushed.append(kind))
    apps.push_prompt_undo(b, "tmpl")
    apps.push_settings_undo(b)
    assert pushed == ["prompt", "settings"]
    b2 = bridge_wiring(undo_service=None)                       # broken service: no raise
    apps.push_prompt_undo(b2, "tmpl")
    apps.push_settings_undo(b2)
