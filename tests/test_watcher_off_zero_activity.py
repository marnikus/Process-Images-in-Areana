"""S2 / D-23 — with the Watcher OFF a visible dialog produces ZERO side effects.

Counting test + positive control (anti-gaming rule 3): the same spies with the
switch ON must count > 0, otherwise this file would pass with the feature deleted.
"""

from types import SimpleNamespace

import pytest

from app.services import single_job_runner as sjr
from app.services.captcha import service
from app.services.captcha.service import CaptchaCtx


class Spy:
    """Records every captcha side effect the pipeline can produce."""

    def __init__(self):
        self.probes = 0
        self.waiting = 0
        self.stats = []
        self.penalties = 0
        self.logs = []

    def log(self, msg, level="info"):
        self.logs.append(msg)


def arm(monkeypatch, spy):
    async def fake_detect(ctx):
        spy.probes += 1
        from app.services.captcha.signals import CaptchaSignal
        return CaptchaSignal(visible=True, kind="recaptcha", page_url="https://arena.ai/x")

    monkeypatch.setattr(service, "detect_signal", fake_detect)
    monkeypatch.setattr(service, "_mark_waiting", lambda ctx: setattr(spy, "waiting", spy.waiting + 1))
    monkeypatch.setattr(service, "_record_stats", lambda ctx, ev, site="": spy.stats.append(ev))
    monkeypatch.setattr(service, "_record_penalty", lambda ctx: setattr(spy, "penalties", spy.penalties + 1))


def make_captcha_ctx(spy, enabled):
    state = {"watcher_enabled": enabled}
    bridge = SimpleNamespace(
        config=SimpleNamespace(get_state=lambda n, d=None: state.get(n, d)),
        _captcha_watcher=None,
        _captcha_service=lambda: None,
        _log=spy.log,
        _emit_pool_status=lambda: None,
    )
    return CaptchaCtx(ctrl=SimpleNamespace(), pool=None, bridge=bridge, tab_id="t1",
                      log=lambda m, l="info": spy.log(m, l))


@pytest.mark.unit
def test_watcher_off_produces_no_captcha_side_effects(event_loop, monkeypatch):
    spy = Spy()
    arm(monkeypatch, spy)

    outcome = event_loop.run_until_complete(service.handle_captcha(make_captcha_ctx(spy, False)))

    assert outcome.status == "out_of_scope"
    assert (spy.probes, spy.waiting, spy.penalties) == (0, 0, 0)
    assert spy.stats == []
    assert [m for m in spy.logs if "🛡" in m or "CAPTCHA_" in m] == []


@pytest.mark.unit
def test_positive_control_watcher_on_does_everything(event_loop, monkeypatch):
    spy = Spy()
    arm(monkeypatch, spy)

    outcome = event_loop.run_until_complete(service.handle_captcha(make_captcha_ctx(spy, True)))

    assert outcome.status in ("manual", "stopped")   # fail-open wait, instantly cleared
    assert spy.probes == 1
    assert spy.waiting == 1
    assert "detected" in spy.stats
    assert any("🛡" in m for m in spy.logs)


@pytest.mark.unit
def test_watcher_off_check_security_does_not_even_probe(event_loop):
    """The second gate: no visibility probe with the switch OFF."""
    visible_calls = []

    async def fake_visible():
        visible_calls.append(1)
        return True

    ctx = SimpleNamespace(ctrl=SimpleNamespace(is_security_dialog_visible=fake_visible),
                          bridge=make_captcha_ctx(Spy(), False).bridge)
    assert event_loop.run_until_complete(sjr.check_security(ctx)) is False
    assert visible_calls == []


@pytest.mark.unit
def test_watcher_off_never_installs_the_security_settler(event_loop, tmp_path, monkeypatch):
    """The third gate: no settler ⇒ the wait loop never runs a captcha settle."""
    from tests.test_single_job_runner import make_client, make_ctx, make_ctrl, make_img

    seen = {}

    async def wait_script(*_a, **_k):
        # runs INSIDE wait_for_output — captures whether a settler is armed mid-wait
        seen["settler"] = getattr(wait_script.ctrl, "security_settler", "ABSENT")
        return "timeout", {"error": "timed out"}

    wait_script.ctrl = make_ctrl(wait_for_new_output=wait_script)
    bridge = make_captcha_ctx(Spy(), False).bridge
    ctx = make_ctx(bridge, wait_script.ctrl, make_client(), make_img(tmp_path))

    assert event_loop.run_until_complete(sjr.wait_for_output(ctx, 1000)) == (None, None, "timed out")
    assert seen["settler"] == "ABSENT"


@pytest.mark.unit
def test_positive_control_watcher_on_installs_the_settler(event_loop, tmp_path):
    from tests.test_single_job_runner import (make_bridge, make_client, make_ctx,
                                              make_ctrl, make_img)
    seen = {}

    async def wait_script(*_a, **_k):
        seen["settler"] = getattr(wait_script.ctrl, "security_settler", "ABSENT")
        return "timeout", {"error": "timed out"}

    wait_script.ctrl = make_ctrl(wait_for_new_output=wait_script)
    ctx = make_ctx(make_bridge(), wait_script.ctrl, make_client(), make_img(tmp_path))

    assert event_loop.run_until_complete(sjr.wait_for_output(ctx, 1000)) == (None, None, "timed out")
    assert callable(seen["settler"])
