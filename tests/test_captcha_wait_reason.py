"""D-15: the overlay WHY line tells the truth about who clears the dialog (S3).

Solving words appear only with a stored key AND a running loop; otherwise the
wait names Chrome and the paused generation timeout.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.services.captcha.policy import pause_cap_seconds, wait_reason
from app.services.captcha.service import CaptchaCtx, handle_captcha
from tests.test_captcha_service import FakeCtrl, make_bridge, make_info


def keyed_bridge(pool, config_dir, api_key="", running=False, session=None):
    bridge = make_bridge(pool, config_dir)
    if session:
        base = bridge.config.get_state
        state = dict(session)

        def get_state(k, d=None):
            if k in state:
                return state[k]
            return base(k, d)

        bridge.config.get_state = get_state
    if running:
        bridge._captcha_watcher = SimpleNamespace(running=True)
    if api_key:
        bridge._captcha_service().apply_settings(api_key, 300)
    return bridge


def instant_sleep(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.mark.unit
def test_on_with_key_says_the_watcher_is_solving(isolated_config_dir):
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = keyed_bridge(pool, isolated_config_dir, api_key="TESTKEY", running=True,
                          session={"watcher_enabled": True})
    assert wait_reason(bridge) == "Captcha Watcher is solving it (2Captcha SDK)"


@pytest.mark.unit
def test_on_without_key_says_solve_it_in_chrome(isolated_config_dir):
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = keyed_bridge(pool, isolated_config_dir,
                          session={"watcher_enabled": True})
    reason = wait_reason(bridge)
    assert "solve it in Chrome" in reason
    assert "generation timeout" in reason
    # A key without the loop must not promise solving either.
    pool2 = PagePool()
    pool2.add_page(make_info("t1"))
    keyed = keyed_bridge(pool2, isolated_config_dir, api_key="TESTKEY",
                         session={"watcher_enabled": True})
    assert "solve it in Chrome" in wait_reason(keyed)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_off_never_reaches_the_wording(monkeypatch, isolated_config_dir):
    import app.services.captcha.service as svc_mod

    instant_sleep(monkeypatch)
    calls = []
    real = svc_mod.wait_reason

    def spy(bridge):
        calls.append(1)
        return real(bridge)

    monkeypatch.setattr(svc_mod, "wait_reason", spy)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.mark_busy("t1", "j1")
    off = make_bridge(pool, isolated_config_dir)
    off.config.get_state = lambda k, d=None: {"watcher_captcha_timeout_sec": 300}.get(k, d)
    outcome = await handle_captcha(CaptchaCtx(ctrl=FakeCtrl(visible_seq=[True] * 5),
                                              pool=pool, bridge=off, tab_id="t1"))
    assert outcome.status == "out_of_scope"
    assert calls == []
    on = keyed_bridge(pool, isolated_config_dir, session={"watcher_enabled": True})
    outcome = await handle_captcha(CaptchaCtx(ctrl=FakeCtrl(visible_seq=[True, False]),
                                              pool=pool, bridge=on, tab_id="t1"))
    assert outcome.status == "manual"
    assert calls == [1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_overlay_receives_timeout_and_sub(monkeypatch, isolated_config_dir):
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.mark_busy("t1", "j1")
    bridge = keyed_bridge(pool, isolated_config_dir,
                          session={"watcher_enabled": True,
                                   "watcher_captcha_timeout_sec": 120})
    ctrl = FakeCtrl(visible_seq=[True, False])
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "manual"
    shown = ctrl.overlay_calls[-1]
    assert shown["timeout_sec"] == 120
    assert shown["timeout_sec"] == pause_cap_seconds(bridge)
    assert shown["sub"] == wait_reason(bridge)
