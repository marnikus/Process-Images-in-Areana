"""S2/S3 policy units. Dependency doubles are only config, clock and key storage."""
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.services.captcha import policy

pytestmark = pytest.mark.unit


def bridge(values=None):
    return NS(config=NS(get_state=lambda k, d=None: (values or {}).get(k, d)))


@pytest.mark.target('app.services.captcha.policy:watcher_enabled')
@pytest.mark.parametrize('value,broken,expected', [(True, False, True), (False, False, False),
                                                 (None, False, False), (True, True, False)])
def test_watcher_enabled(value, broken, expected):
    host = bridge({'watcher_enabled': value})
    if broken:
        host.config.get_state = Mock(side_effect=RuntimeError('unreadable'))
    assert policy.watcher_enabled(host) is expected


@pytest.mark.target('app.services.captcha.policy:captcha_in_scope')
@pytest.mark.parametrize('running', [None, False, True])
@pytest.mark.parametrize('key', ['', 'configured'])
def test_captcha_in_scope(running, key):
    settings = {'watcher_enabled': False}
    host = bridge(settings)
    host._captcha_watcher = None if running is None else NS(running=running)
    host._captcha_service = lambda: NS(keys=NS(load=lambda: NS(provider='active', key_for=lambda p: key)))
    for on in [False, True, False]:
        settings['watcher_enabled'] = on
        assert policy.captcha_in_scope(host) is on


@pytest.mark.target('app.services.captcha.policy:solver_running')
@pytest.mark.parametrize('state,expected', [('missing', False), (False, False), (True, True), ('broken', False)])
def test_solver_running(state, expected):
    class BrokenWatcher:
        @property
        def running(self):
            raise RuntimeError('unreadable')
    host = NS()
    if state != 'missing':
        host._captcha_watcher = BrokenWatcher() if state == 'broken' else NS(running=state)
    assert policy.solver_running(host) is expected


@pytest.mark.target('app.services.captcha.policy:has_solver_key')
@pytest.mark.parametrize('state,expected', [('key', True), ('empty', False), ('missing', False), ('broken', False)])
def test_has_solver_key(state, expected):
    requested = []
    host = NS()
    if state != 'missing':
        load = Mock(return_value=NS(provider='active', key_for=lambda p: requested.append(p) or ('key' if state == 'key' else '')))
        host._captcha_service = Mock(return_value=NS(keys=NS(load=load)))
        if state == 'broken':
            host._captcha_service.side_effect = RuntimeError('unreadable')
    assert policy.has_solver_key(host) is expected
    if state in ('key', 'empty'):
        assert requested == ['active']


@pytest.mark.target('app.services.captcha.policy:out_of_scope')
def test_out_of_scope():
    outcome = policy.out_of_scope()
    assert (outcome.status, outcome.reason) == ('out_of_scope', 'watcher off')


@pytest.mark.target('app.services.captcha.policy:pause_cap_seconds')
@pytest.mark.parametrize('raw,expected', [(None, 300), ('bad', 300), (0, 10), (10, 10), (4000, 3600), (45, 45)])
def test_pause_cap_seconds(raw, expected):
    assert policy.pause_cap_seconds(bridge({'watcher_captcha_timeout_sec': raw})) == expected


@pytest.mark.target('app.services.captcha.policy:wait_reason')
@pytest.mark.parametrize('key', ['', 'stored-key'])
def test_wait_reason(key):
    host = bridge({'watcher_enabled': True})
    host._captcha_service = lambda: NS(keys=NS(load=lambda: NS(provider='active', key_for=lambda p: key)))
    text = policy.wait_reason(host)
    if key:
        assert text == 'Captcha Watcher is solving it (2Captcha SDK)'
    else:
        assert 'solve it in Chrome' in text and 'timeout is paused' in text
        assert 'solving' not in text.lower()


@pytest.mark.target('app.services.captcha.policy:WaitDeadline.__init__')
@pytest.mark.parametrize('cap', [0, 10, '300'])
def test_deadline_init(monkeypatch, cap):
    monkeypatch.setattr(policy.time, 'monotonic', lambda: 100)
    deadline = policy.WaitDeadline(cap)
    assert (deadline.cap_s, deadline.start) == (float(cap), 100)


@pytest.mark.target('app.services.captcha.policy:WaitDeadline.expired')
@pytest.mark.parametrize('cap,elapsed,expected', [(10, 9, False), (10, 10, True), (10, 11, True), (0, 999, False)])
def test_deadline_expired(monkeypatch, cap, elapsed, expected):
    now = [100]
    monkeypatch.setattr(policy.time, 'monotonic', lambda: now[0])
    deadline = policy.WaitDeadline(cap)
    now[0] += elapsed
    assert deadline.expired() is expected


@pytest.mark.target('app.services.captcha.policy:WaitDeadline.stop_or')
@pytest.mark.parametrize('elapsed,stop,expected', [(0, None, False), (0, False, False), (0, True, True), (10, False, True)])
def test_deadline_stop_or(monkeypatch, elapsed, stop, expected):
    now = [100]
    monkeypatch.setattr(policy.time, 'monotonic', lambda: now[0])
    deadline = policy.WaitDeadline(10)
    callback = None if stop is None else Mock(return_value=stop)
    combined = deadline.stop_or(callback)
    now[0] += elapsed
    assert combined() is expected
    if elapsed == 10:
        callback.assert_not_called()
