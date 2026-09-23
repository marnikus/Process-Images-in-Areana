"""S3 · D-15 wording — `policy.wait_reason(bridge)` says who is expected to
clear the dialog, and the overlay countdown is the same number as the cap
(D-14R: "the cap is visible while it runs").

The key and the solver loop pick the *wording*; they never widen scope (S2).
"""

from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.services.captcha import policy
from app.services.captcha.service import CaptchaCtx, CaptchaService, handle_captcha
from tests.test_captcha_service import FakeCtrl, instant_sleep, make_info

pytestmark = pytest.mark.unit


def bridge_with(session, key="", running=True, config_dir=None):
    logs = []
    bridge = SimpleNamespace(
        config=SimpleNamespace(get_state=lambda k, d=None: session.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: None,
        _captcha_watcher=SimpleNamespace(running=running),
        _logs=logs,
    )
    if config_dir is not None:
        service = CaptchaService(str(config_dir), bridge._log)
        service.apply_settings(key, 300)
        bridge._captcha_service = lambda: service
    return bridge


def test_on_with_key_says_the_watcher_is_solving(isolated_config_dir):
    bridge = bridge_with({"watcher_enabled": True}, key="k" * 32, config_dir=isolated_config_dir)
    assert policy.has_solver_key(bridge) is True
    text = policy.wait_reason(bridge)
    assert "Captcha Watcher is solving" in text
    assert "k" * 32 not in text  # RULE 20: never the key itself


def test_on_without_key_says_solve_it_in_chrome(isolated_config_dir):
    bridge = bridge_with({"watcher_enabled": True}, key="", config_dir=isolated_config_dir)
    assert policy.has_solver_key(bridge) is False
    text = policy.wait_reason(bridge)
    assert "solve it in Chrome" in text
    assert "solving" not in text  # never promise a solve without a key
    assert "paused" in text and "generation timeout" in text
    # no captcha service on the bridge at all ⇒ same honest wording
    assert policy.wait_reason(bridge_with({"watcher_enabled": True})) == text


@pytest.mark.asyncio
async def test_off_never_reaches_the_wording(monkeypatch, isolated_config_dir):
    """S2's gate returns first: OFF never asks who would solve."""
    instant_sleep(monkeypatch)
    calls = []
    monkeypatch.setattr(policy, "wait_reason", lambda b: calls.append(b) or "never")
    pool = PagePool()
    pool.add_page(make_info("t1"))
    bridge = bridge_with({"watcher_enabled": False}, key="k" * 32, config_dir=isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, False])
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "out_of_scope"
    assert calls == [] and ctrl.overlay_calls == []


@pytest.mark.asyncio
async def test_the_overlay_receives_timeout_and_sub(monkeypatch, isolated_config_dir):
    """The visible countdown and the cap are the same number; the WHY line is `wait_reason`."""
    instant_sleep(monkeypatch)
    pool = PagePool()
    pool.add_page(make_info("t1"))
    session = {"watcher_enabled": True, "watcher_captcha_timeout_sec": 45}
    bridge = bridge_with(session, key="", config_dir=isolated_config_dir)
    ctrl = FakeCtrl(visible_seq=[True, False])
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "manual"
    overlay = ctrl.overlay_calls[-1]
    assert overlay["timeout_sec"] == policy.pause_cap_seconds(bridge) == 45
    assert overlay["sub"] == policy.wait_reason(bridge)
    assert overlay["kind"] == "captcha"
