"""D-15 — the overlay's wait reason has one owner: `policy.wait_reason(bridge)`.

Watcher ON + key ⇒ the Watcher is solving; ON + no key ⇒ solve it in Chrome
(and the generation timeout is paused). OFF never reaches the wording
(S2's gate answers first). Real key store on an isolated config dir.
"""

from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.services.captcha import policy
from app.services.captcha import service as svc_mod
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha
from tests.test_captcha_service import FakeCtrl, instant_sleep, make_info

pytestmark = pytest.mark.unit

KEY = "abcdefghijklmnop1234567890abcdef"


def make_bridge(config_dir, running=True, key=None, on=True):
    state = {"watcher_enabled": on, "watcher_captcha_timeout_sec": 300}
    service = CaptchaService(str(config_dir))
    if key:
        service.apply_settings(key, 300)
    return SimpleNamespace(
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _captcha_watcher=SimpleNamespace(running=running),
        _captcha_service=lambda: service,
        _log=lambda m, l="info": None, _emit_pool_status=lambda: None,
    )


def test_on_with_key_says_the_watcher_is_solving(isolated_config_dir):
    reason = policy.wait_reason(make_bridge(isolated_config_dir, running=True, key=KEY))
    assert reason.startswith("Captcha Watcher is solving")


def test_on_without_key_says_solve_it_in_chrome(isolated_config_dir):
    reason = policy.wait_reason(make_bridge(isolated_config_dir, running=True, key=None))
    assert "solve it in Chrome" in reason and "timeout is paused" in reason
    assert "solving" not in reason
    stalled = policy.wait_reason(make_bridge(isolated_config_dir, running=False, key=KEY))
    assert "solve it in Chrome" in stalled and "solving" not in stalled   # key, but no solver loop


async def test_off_never_reaches_the_wording(monkeypatch, isolated_config_dir):
    calls = []
    monkeypatch.setattr(svc_mod, "wait_reason", lambda bridge: calls.append(bridge) or "x")
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(isolated_config_dir, on=False)
    outcome = await handle_captcha(CaptchaCtx(ctrl=FakeCtrl(visible_seq=[True]), pool=pool,
                                              bridge=bridge, tab_id="t1"))
    assert outcome.status == "out_of_scope" and calls == []


async def test_the_overlay_receives_timeout_and_sub(monkeypatch, isolated_config_dir):
    """The visible countdown and the cap are the same number; the sub is the policy's wording."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = make_bridge(isolated_config_dir, running=True, key=None)
    ctrl = FakeCtrl(visible_seq=[True, False])
    await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    call = ctrl.overlay_calls[-1]
    assert call["timeout_sec"] == policy.pause_cap_seconds(bridge) == 300
    assert call["sub"] == policy.wait_reason(bridge)
    assert call["kind"] == "captcha"
