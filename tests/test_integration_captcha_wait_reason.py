# Integration/contract lane: real collaborators; not counted as function units.
"""S3 — D-15: one pure helper owns the wait-reason wording.

Watcher ON + key ⇒ the Watcher is solving; Watcher ON + no key ⇒ solve it in
Chrome AND say the timeout is paused (today's no-key line tells the user to
turn the Watcher ON while it is ON — a lie in the UI); Watcher OFF never
reaches the wording (S2's gate returns first).
"""

import json
from types import SimpleNamespace


from app.services.captcha import policy
from app.services.captcha.service import CaptchaCtx, handle_captcha

import pytest

pytestmark = pytest.mark.integration


DETECT = json.dumps({"visible": True, "kind": "recaptcha_v2",
                     "sitekey": "sk", "url": "https://arena.ai"})


def make_bridge(key: str, watcher_on=True, collector=None):
    logs = collector if collector is not None else []
    settings = SimpleNamespace(provider="recaptcha", key_for=lambda p: key)
    svc = SimpleNamespace(
        stats=SimpleNamespace(record=lambda e, s="": None),
        keys=SimpleNamespace(load=lambda: settings),
        recordings=SimpleNamespace(
            start=lambda *a, **k: _arec(), finish=lambda *a, **k: _arec(),
            abort=lambda *a, **k: _arec()))
    state = {"watcher_enabled": watcher_on, "watcher_captcha_timeout_sec": 300,
             "cooldown_captcha_penalty_seconds": 900}
    return SimpleNamespace(
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _page_pool=SimpleNamespace(mark_waiting=lambda *a: None),
        _emit_pool_status=lambda: None,
        _log=lambda m, l="info": logs.append(m),
        _captcha_service=lambda: svc,
    )


async def _arec():
    return None


def make_ctrl(visible_seq, overlay_calls):
    seq = list(visible_seq)

    async def evaluate(js):
        return DETECT

    async def dialog_visible():
        return seq.pop(0) if seq else False

    async def overlay(text, kind=None, timeout_sec=None, sub=None):
        overlay_calls.append({"timeout_sec": timeout_sec, "sub": sub})
        return True

    async def hide():
        return True

    return SimpleNamespace(cdp=SimpleNamespace(evaluate=evaluate),
                           is_security_dialog_visible=dialog_visible,
                           show_watcher_overlay=overlay, hide_watcher_overlay=hide)


@pytest.mark.asyncio
async def test_off_never_reaches_the_wording(monkeypatch):
    called = []
    monkeypatch.setattr(policy, "wait_reason",
                        lambda b: called.append(1) or "wording")
    bridge = make_bridge(key="sk-abc", watcher_on=False)
    ctrl = make_ctrl([True, False], [])
    ctx = CaptchaCtx(ctrl=ctrl, pool=bridge._page_pool, bridge=bridge, tab_id="t1",
                     source="check-security", log=lambda m, l="info": None)

    outcome = await handle_captcha(ctx)
    assert outcome.status == "out_of_scope"  # S2's gate returns first
    assert called == []


@pytest.mark.asyncio
async def test_the_overlay_receives_timeout_and_sub(monkeypatch):
    import app.services.cooldown_service as cooldown
    monkeypatch.setattr(cooldown, "_POLL_SEC", 0)
    overlay_calls = []
    bridge = make_bridge(key="sk-abc")
    ctrl = make_ctrl([True, False], overlay_calls)  # clears on the second poll
    ctx = CaptchaCtx(ctrl=ctrl, pool=bridge._page_pool, bridge=bridge, tab_id="t1",
                     source="check-security", log=lambda m, l="info": None)

    outcome = await handle_captcha(ctx)
    assert outcome.status == "manual"
    shown = overlay_calls[0]
    assert shown["timeout_sec"] == policy.pause_cap_seconds(bridge)
    assert shown["sub"] == policy.wait_reason(bridge)
