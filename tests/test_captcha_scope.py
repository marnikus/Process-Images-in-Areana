"""Watcher scope is a hard captcha gate (S2): OFF means zero captcha activity.

RULE 8: real `policy` predicates + real `PagePool`; only CDP/bridge faked.
Host bridges are SimpleNamespaces with a `config` stub, like
`test_captcha_boundaries.make_bridge` (session override dict).
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import single_job_runner as sjr
from app.services.captcha import policy
from app.services.captcha.service import CaptchaCtx, _watcher_running
from tests.test_captcha_service import FakeCtrl

URL = "https://arena.ai/image/direct"


def make_info(tab_id):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url=URL, status=PageStatus.STEADY, is_connected=True)


def make_bridge(pool=None, session=None):
    state = dict(session or {})
    logs = []
    return SimpleNamespace(
        _cancel_requested=False,
        _page_pool=pool,
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        _emit_job_action_status=lambda action: logs.append(
            (getattr(action.block, "block_id", action.block),
             action.status, action.message)),
        _logs=logs,
        _state=state,
    )


def make_visible_ctrl(seq):
    calls = []

    async def fake_visible():
        calls.append("visible")
        return seq.pop(0) if seq else False

    async def fake_overlay(*a, **k):
        calls.append("overlay")

    async def fake_hide(*a, **k):
        calls.append("hide")

    ctrl = SimpleNamespace(
        is_security_dialog_visible=fake_visible,
        show_watcher_overlay=fake_overlay,
        hide_watcher_overlay=fake_hide,
    )
    return ctrl, calls


def make_spy_service():
    stats_calls = []
    rec_calls = []

    async def _start(ctrl, rep):
        rec_calls.append("start")
        return None

    async def _finish(recorder, outcome, rep):
        rec_calls.append("finish")

    async def _abort(recorder, reason):
        rec_calls.append("abort")

    svc = SimpleNamespace(
        stats=SimpleNamespace(record=lambda e, s="": stats_calls.append(e)),
        recordings=SimpleNamespace(start=_start, finish=_finish, abort=_abort),
    )
    return svc, stats_calls, rec_calls


def instant_sleep(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


@pytest.mark.unit
def test_watcher_enabled_mirrors_the_switch():
    assert policy.watcher_enabled(make_bridge(session={"watcher_enabled": True})) is True
    assert policy.watcher_enabled(make_bridge(session={})) is False

    def boom(_k, _d=None):
        raise RuntimeError("config gone")

    raising = SimpleNamespace(config=SimpleNamespace(get_state=boom))
    assert policy.watcher_enabled(raising) is False


@pytest.mark.unit
def test_captcha_in_scope_is_the_switch_and_nothing_else():
    def keyed(api_key):
        return SimpleNamespace(keys=SimpleNamespace(
            load=lambda: SimpleNamespace(api_key=api_key)))

    running = SimpleNamespace(running=True)
    on = {"watcher_enabled": True}
    off = {"watcher_enabled": False}
    # Scope follows the switch in all four key/loop combinations ...
    assert policy.captcha_in_scope(make_bridge(session=on)) is True
    assert policy.captcha_in_scope(make_bridge(session=off)) is False
    b = make_bridge(session=on)
    b._captcha_watcher = running
    b._captcha_service = lambda: keyed("TESTKEY")
    assert policy.captcha_in_scope(b) is True
    b = make_bridge(session=off)
    b._captcha_watcher = running
    b._captcha_service = lambda: keyed("TESTKEY")
    assert policy.captcha_in_scope(b) is False
    # ... while the helpers themselves still report their own state.
    assert policy.has_solver_key(b) is True
    assert policy.solver_running(b) is True
    assert policy.has_solver_key(make_bridge(session=on)) is False
    b2 = make_bridge(session=on)
    b2._captcha_service = lambda: keyed("")
    assert policy.has_solver_key(b2) is False

    def boom():
        raise RuntimeError("store gone")

    b3 = make_bridge(session=on)
    b3._captcha_service = lambda: SimpleNamespace(keys=SimpleNamespace(load=boom))
    assert policy.has_solver_key(b3) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_check_security_does_not_probe_when_off(monkeypatch):
    instant_sleep(monkeypatch)
    bridge = make_bridge()
    ctrl, calls = make_visible_ctrl([True, False])
    ctx = SimpleNamespace(bridge=bridge, ctrl=ctrl, tab_id="t1")
    assert await sjr.check_security(ctx) is False
    assert calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_security_block_reports_skipped_when_off():
    bridge = make_bridge()
    ctrl, calls = make_visible_ctrl([True, False])
    ctx = SimpleNamespace(bridge=bridge, ctrl=ctrl, job_id="j1")
    await sjr._handle_security(ctx, SimpleNamespace(block_id="CHECK_SECURITY"))
    pairs = [(b, s) for b, s, _m in bridge._logs if b == "CHECK_SECURITY"]
    assert pairs == [("CHECK_SECURITY", "success")]
    assert bridge._logs[-1][2] == "Skipped (Watcher off)"
    assert calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_handle_captcha_returns_out_of_scope_when_off(monkeypatch):
    instant_sleep(monkeypatch)
    from app.services.captcha.service import handle_captcha
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.mark_busy("t1", "j1")
    bridge = make_bridge(pool)
    svc, stats_calls, rec_calls = make_spy_service()
    bridge._captcha_service = lambda: svc
    ctrl = FakeCtrl(visible_seq=[True] * 50)
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "out_of_scope"
    assert outcome.reason == "watcher off"
    assert ctrl.probes == []
    assert ctrl.overlay_calls == []
    assert stats_calls == []
    assert rec_calls == []
    assert not any("🛡️" in m for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_settler_is_not_installed_when_off(monkeypatch):
    seen = []
    bridge = make_bridge()

    async def fake_overlay(*a, **k):
        return True

    ctrl = SimpleNamespace(show_watcher_overlay=fake_overlay,
                           hide_watcher_overlay=fake_overlay)

    async def fake_poll(ctx, timeout_ms):
        seen.append(hasattr(ctx.ctrl, "security_settler"))
        return "timeout", {"error": "timed out"}, None

    monkeypatch.setattr(sjr, "_poll_generation", fake_poll)
    ctx = sjr.JobCtx(bridge=bridge, ctrl=ctrl, client=None, tab_id="t1",
                     img=None, urls=[], job_id="j1", corr_id="c1",
                     final_prompt="p", baseline={"output_count": 0, "output_srcs": []})
    assert await sjr.wait_for_output(ctx, 1000) == (None, None, "timed out")
    assert seen == [False]
    assert hasattr(ctrl, "security_settler") is False
    # The same wait WITH the switch ON still installs (and removes) the settler.
    bridge._state["watcher_enabled"] = True
    assert await sjr.wait_for_output(ctx, 1000) == (None, None, "timed out")
    assert seen == [False, True]
    assert hasattr(ctrl, "security_settler") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scope_is_evaluated_per_call():
    bridge = make_bridge()

    async def never():
        calls.append("visible")
        return False

    calls = []
    ctrl = SimpleNamespace(is_security_dialog_visible=never)
    ctx = SimpleNamespace(bridge=bridge, ctrl=ctrl, tab_id="t1")
    assert await sjr.check_security(ctx) is False
    assert calls == []
    bridge._state["watcher_enabled"] = True
    assert await sjr.check_security(ctx) is False
    assert calls == ["visible"]


@pytest.mark.unit
def test_watcher_running_delegates_to_policy():
    class Raising:
        @property
        def running(self):
            raise RuntimeError("loop gone")

    cases = [
        ("absent", None, False),
        ("stopped", SimpleNamespace(running=False), False),
        ("running", SimpleNamespace(running=True), True),
        ("raising", Raising(), False),
    ]
    for _name, watcher, want in cases:
        bridge = make_bridge()
        if watcher is not None:
            bridge._captcha_watcher = watcher
        ctx = CaptchaCtx(ctrl=None, pool=None, bridge=bridge, tab_id="t")
        assert _watcher_running(ctx) is want
        assert policy.solver_running(bridge) is want
