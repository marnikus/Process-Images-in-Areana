"""S2 — the scope predicate is the switch, and nothing else."""

from types import SimpleNamespace

import pytest

from app.services.captcha import policy


def make_bridge(session=None, watcher=None, key=False):
    state = dict(session or {})

    class Cfg:
        def get_state(self, name, default=None):
            return state.get(name, default)

    class Keys:
        def load(self):
            return SimpleNamespace(api_key="deadbeef" if key else "")

    return SimpleNamespace(
        config=Cfg(),
        _captcha_watcher=watcher,
        _captcha_service=lambda: SimpleNamespace(keys=Keys()),
    )


@pytest.mark.unit
def test_watcher_enabled_mirrors_the_switch():
    assert policy.watcher_enabled(make_bridge({"watcher_enabled": True})) is True
    assert policy.watcher_enabled(make_bridge({})) is False          # fail-closed default


@pytest.mark.unit
def test_watcher_enabled_is_fail_closed_on_a_broken_config():
    class Boom:
        def get_state(self, *_a, **_k):
            raise RuntimeError("config gone")

    assert policy.watcher_enabled(SimpleNamespace(config=Boom())) is False


@pytest.mark.unit
@pytest.mark.parametrize("running", [True, False])
@pytest.mark.parametrize("key", [True, False])
def test_captcha_in_scope_is_the_switch_and_nothing_else(running, key):
    on = make_bridge({"watcher_enabled": True}, SimpleNamespace(running=running), key)
    off = make_bridge({"watcher_enabled": False}, SimpleNamespace(running=running), key)
    assert policy.captcha_in_scope(on) is True
    assert policy.captcha_in_scope(off) is False


@pytest.mark.unit
def test_solver_running_is_fail_closed_without_a_watcher():
    assert policy.solver_running(make_bridge({})) is False
    assert policy.solver_running(make_bridge({}, SimpleNamespace(running=True))) is True


@pytest.mark.unit
def test_has_solver_key_never_touches_the_key_material():
    """True/False from the stored key's presence; the key text is never read out."""
    assert policy.has_solver_key(make_bridge({}, key=True)) is True
    assert policy.has_solver_key(SimpleNamespace()) is False


@pytest.mark.unit
def test_out_of_scope_is_an_outcome_not_none():
    outcome = policy.out_of_scope()
    assert outcome.status == "out_of_scope"
    assert outcome.reason == "watcher off"
