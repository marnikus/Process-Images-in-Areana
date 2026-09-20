"""S3 — D-15: the overlay's amber reason line tells the truth.

Before: Watcher ON without a key told the user to "turn the Watcher ON".
Now one helper, `policy.wait_reason(bridge)`, owns the words; the overlay
countdown and the pause cap are the same number (`watcher_captcha_timeout_sec`).
"""

from types import SimpleNamespace

import pytest

from app.services.captcha.policy import wait_reason
from test_captcha_service import (
    FakeCtrl, instant_sleep, make_bridge, make_info,
)
from app.browser.page_pool import PagePool


def bridge_with(pool, config_dir, state):
    bridge = make_bridge(pool, config_dir)
    bridge.config = SimpleNamespace(get_state=lambda k, d=None: state.get(k, d))
    return bridge


def store_a_key(config_dir):
    """The key lives in the on-disk key store, not in config state."""
    from app.services.captcha.key_store import CaptchaKeyStore, CaptchaSettings

    CaptchaKeyStore(config_dir).save(CaptchaSettings(api_key="K" * 16))


@pytest.mark.unit
def test_watcher_on_with_a_key_says_the_watcher_is_solving(isolated_config_dir):
    store_a_key(isolated_config_dir)
    pool = PagePool()
    bridge = bridge_with(pool, isolated_config_dir,
                         {"watcher_enabled": True, "watcher_captcha_timeout_sec": 300})
    assert wait_reason(bridge) == "Captcha Watcher is solving it (2Captcha SDK)"


@pytest.mark.unit
def test_watcher_on_without_a_key_says_solve_it_in_chrome(isolated_config_dir):
    pool = PagePool()
    bridge = bridge_with(pool, isolated_config_dir,
                         {"watcher_enabled": True, "watcher_captcha_timeout_sec": 300})
    reason = wait_reason(bridge)
    assert reason == ("Watcher ON, no 2Captcha key — solve it in Chrome; "
                      "this job's timeout is paused")
    assert "turn the Watcher ON" not in reason   # the pre-S3 lie is gone


@pytest.mark.unit
@pytest.mark.asyncio
async def test_watcher_off_never_reaches_the_wording(monkeypatch, isolated_config_dir):
    """Out of scope returns first: wait_reason is never even asked."""
    from app.services.captcha import service as captcha_service

    monkeypatch.setattr(captcha_service, "wait_reason",
                        lambda _b: pytest.fail("wait_reason called while Watcher OFF"))
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = bridge_with(pool, isolated_config_dir, {"watcher_enabled": False})
    ctrl = FakeCtrl(visible_seq=[True, False])

    from app.services.captcha.service import CaptchaCtx, handle_captcha
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))

    assert outcome.status == "out_of_scope"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_overlay_receives_the_cap_and_the_reason(monkeypatch, isolated_config_dir):
    """D-14R's 'the cap is visible while it runs': the overlay's countdown and
    the pause cap are the same number."""
    instant_sleep(monkeypatch)
    store_a_key(isolated_config_dir)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = bridge_with(pool, isolated_config_dir,
                         {"watcher_enabled": True, "watcher_captcha_timeout_sec": 234})
    ctrl = FakeCtrl(visible_seq=[True, False])

    from app.services.captcha.service import CaptchaCtx, handle_captcha
    await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))

    assert ctrl.overlay_calls, "no overlay was shown while waiting"
    overlay = ctrl.overlay_calls[-1]
    assert overlay["timeout_sec"] == 234
    assert overlay["sub"] == wait_reason(bridge)
