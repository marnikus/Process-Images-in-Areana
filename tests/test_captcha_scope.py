"""S2 · Captcha scope — one predicate owns "is captcha work allowed right now?".

`app/services/captcha/policy.py` is the only reader of the Watcher switch
(I-48). Five existing gates ask it: `check_security`, `_handle_security`,
`wait_for_output` (settler install), `handle_captcha` (choke gate) and
`_watcher_running`. RULE 8: the subject (the predicate and the gates) is
real; only the CDP controller and the bridge are fakes (tdd-interfaces §E.2).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import single_job_runner as sjr
from app.services.captcha import policy, service
from app.services.captcha.service import CaptchaCtx, handle_captcha

from tests.test_single_job_runner import make_bridge as make_runner_bridge
from tests.test_single_job_runner import make_ctrl as make_runner_ctrl
from tests.test_single_job_runner import make_block, make_client, make_ctx, make_img

pytestmark = pytest.mark.unit


def make_bridge(session=None, **attrs):
    state = dict(session or {})
    logs = []
    bridge = SimpleNamespace(
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _logs=logs, _state=state,
        _page_pool=None, _emit_pool_status=lambda: None, _cancel_requested=False,
    )
    for key, value in attrs.items():
        setattr(bridge, key, value)
    return bridge


def make_ctrl(visible=True):
    calls = []

    async def fake_visible():
        calls.append("visible")
        return visible

    async def fake_evaluate(js):
        calls.append("detect")
        return {"visible": True, "kind": "recaptcha_v2", "sitekey": "k"}

    async def fake_overlay(*a, **k):
        calls.append("overlay")

    async def fake_hide(*a, **k):
        calls.append("hide")

    ctrl = SimpleNamespace(is_security_dialog_visible=fake_visible,
                           cdp=SimpleNamespace(evaluate=fake_evaluate),
                           show_watcher_overlay=fake_overlay, hide_watcher_overlay=fake_hide)
    return ctrl, calls


def job_ctx(bridge, ctrl):
    img = SimpleNamespace(status="pending", error="", output_path="", relative_path="pic.png")
    return sjr.JobCtx(bridge=bridge, ctrl=ctrl, client=None, tab_id="t1", img=img, urls=[],
                      job_id="j1", corr_id="c1", final_prompt="p")


# --- the predicate ---------------------------------------------------------

def test_watcher_enabled_mirrors_the_switch():
    assert policy.watcher_enabled(make_bridge({"watcher_enabled": True})) is True
    assert policy.watcher_enabled(make_bridge({})) is False, "fail-closed default"

    def boom(k, d=None):
        raise RuntimeError("config down")
    assert policy.watcher_enabled(SimpleNamespace(config=SimpleNamespace(get_state=boom))) is False


def test_captcha_in_scope_is_the_switch_and_nothing_else():
    running = SimpleNamespace(running=True)
    keyed = lambda: SimpleNamespace(keys=SimpleNamespace(load=lambda: SimpleNamespace(api_key="k")))
    for watcher, key in ((None, None), (running, None), (None, keyed), (running, keyed)):
        off = make_bridge({"watcher_enabled": False}, _captcha_watcher=watcher)
        on = make_bridge({"watcher_enabled": True}, _captcha_watcher=watcher)
        if key is not None:
            off._captcha_service = key
            on._captcha_service = key
        assert policy.captcha_in_scope(off) is False
        assert policy.captcha_in_scope(on) is True
        assert policy.solver_running(on) is (watcher is running)
        assert policy.has_solver_key(on) is (key is not None)
    assert policy.out_of_scope().status == "out_of_scope"
    assert policy.out_of_scope().reason == "watcher off"


# --- the five gates --------------------------------------------------------

async def test_check_security_does_not_probe_when_off():
    ctrl, calls = make_ctrl(visible=True)
    assert await sjr.check_security(job_ctx(make_bridge({}), ctrl)) is False
    assert calls == []


async def test_handle_security_block_reports_skipped_when_off():
    ctrl, calls = make_ctrl(visible=True)
    events = []
    bridge = make_bridge({}, _emit_job_action_status=lambda a: events.append(
        (a.block.block_id, a.status, a.message)))
    await sjr._handle_security(job_ctx(bridge, ctrl), make_block("CHECK_SECURITY"))
    assert events == [("CHECK_SECURITY", "success", "Skipped (Watcher off)")]
    assert calls == []


async def test_handle_captcha_returns_out_of_scope_when_off():
    ctrl, calls = make_ctrl(visible=True)
    stats = []
    bridge = make_bridge({}, _captcha_service=lambda: SimpleNamespace(
        stats=SimpleNamespace(record=lambda *a: stats.append(a))))
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=None, bridge=bridge, tab_id="t1"))
    assert (outcome.status, outcome.reason) == ("out_of_scope", "watcher off")
    assert calls == [] and stats == [] and bridge._logs == []


async def test_settler_is_not_installed_when_off(tmp_path, monkeypatch):
    seen = []

    async def fake_poll(ctx, timeout_ms):
        seen.append(hasattr(ctx.ctrl, "security_settler"))
        return "timeout", {"error": "timed out"}, None

    monkeypatch.setattr(sjr, "_poll_generation", fake_poll)
    for enabled in (False, True):
        bridge = make_runner_bridge(session={"watcher_enabled": enabled})
        ctrl = make_runner_ctrl()
        ctx = make_ctx(bridge, ctrl, make_client(), make_img(tmp_path))
        assert await sjr.wait_for_output(ctx, 1000) == (None, None, "timed out")
        assert not hasattr(ctrl, "security_settler"), "settler must be gone after the wait"
    assert seen == [False, True], "installed during the wait only while in scope"


async def test_scope_is_evaluated_per_call():
    ctrl, calls = make_ctrl(visible=False)
    bridge = make_bridge({"watcher_enabled": False})
    ctx = job_ctx(bridge, ctrl)
    assert await sjr.check_security(ctx) is False and calls == []
    bridge._state["watcher_enabled"] = True
    assert await sjr.check_security(ctx) is False
    assert calls == ["visible"], "ON is live without a restart"


def test_watcher_running_delegates_to_policy():
    class Raising:
        @property
        def running(self):
            raise RuntimeError("no loop")

    for watcher in (None, SimpleNamespace(running=False), SimpleNamespace(running=True), Raising()):
        bridge = make_bridge({}, _captcha_watcher=watcher)
        ctx = CaptchaCtx(ctrl=None, pool=None, bridge=bridge, tab_id="t1")
        assert service._watcher_running(ctx) is policy.solver_running(bridge)
    assert policy.solver_running(make_bridge({}, _captcha_watcher=SimpleNamespace(running=True))) is True
