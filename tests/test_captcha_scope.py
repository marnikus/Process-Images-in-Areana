"""S2 — captcha scope: the Watcher switch is the ONE gate for pipeline captcha work.

`app.services.captcha.policy` is the only reader of `watcher_enabled`. With the
switch OFF the pipeline neither probes for a dialog, nor installs the
mid-generation settler, nor enters `handle_captcha`'s body; with it ON the
existing detect → wait → penalty flow is unchanged (S2 adds no solver).

RULE 8: real `single_job_runner` and `captcha.service` entry points; only the
CDP controller and the bridge are fakes. RULE 10: scope is the switch and
nothing else — never the key, never the loop.
Plan: docs/archive/2026-09-20-dynamic-urls-and-worker-debug/tdd-interfaces.md §S2
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import single_job_runner as sjr
from app.services.captcha import policy
from app.services.captcha.service import CaptchaCtx, _watcher_running, handle_captcha

pytestmark = pytest.mark.unit


def make_bridge(session=None, pool=None):
    state = dict(session or {})
    logs = []
    events = []
    return SimpleNamespace(
        _cancel_requested=False,
        _page_pool=pool,
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        state=SimpleNamespace(settings=SimpleNamespace(timeouts={"generation": 180})),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: None,
        _emit_job_action_status=lambda a: events.append((a.block, a.status, a.message)),
        _logs=logs,
        _events=events,
        _session=state,
    )


class CountingCtrl:
    """Dialog always visible; every captcha-related call is counted."""

    def __init__(self, visible_seq=None):
        self.calls = []
        self._visible = list(visible_seq) if visible_seq is not None else None
        self.cdp = SimpleNamespace(evaluate=self._evaluate)

    async def _evaluate(self, js):
        self.calls.append("detect")
        return {"visible": True, "kind": "recaptcha_enterprise", "sitekey": "6Lkey", "url": "https://arena.ai"}

    async def is_security_dialog_visible(self):
        self.calls.append("visible")
        if self._visible:
            return self._visible.pop(0)
        # bounded: a wrongly-scoped wait polls, then sees it clear (never hangs the suite)
        return self.calls.count("visible") < 3

    async def show_watcher_overlay(self, *a, **k):
        self.calls.append("overlay")

    async def hide_watcher_overlay(self, *a, **k):
        self.calls.append("hide")


def make_ctx(bridge, ctrl):
    img = SimpleNamespace(status="pending", error="", output_path="", relative_path="pic.png",
                          absolute_path="/tmp/pic.png")
    return sjr.JobCtx(bridge=bridge, ctrl=ctrl, client=None, tab_id="t1", img=img, urls=[],
                      job_id="j1", corr_id="c1", final_prompt="p [JOB-ID: c1]")


def pool_with_tab():
    pool = PagePool()
    pool.add_page(PageInfo(ws_url="ws://t1", tab_id="t1", title="T", url="https://arena.ai",
                           status=PageStatus.STEADY, is_connected=True))
    pool.mark_busy("t1", "j1")
    return pool


@pytest.fixture(autouse=True)
def instant_sleep(monkeypatch):
    real_sleep = asyncio.sleep

    async def _fast(_s):
        await real_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", _fast)


# ── the predicate ──

def test_watcher_enabled_mirrors_the_switch():
    assert policy.watcher_enabled(make_bridge({"watcher_enabled": True})) is True
    assert policy.watcher_enabled(make_bridge({})) is False  # fail-closed default

    def boom(*_a, **_k):
        raise RuntimeError("config gone")
    assert policy.watcher_enabled(SimpleNamespace(config=SimpleNamespace(get_state=boom))) is False
    assert policy.watcher_enabled(SimpleNamespace()) is False


def test_captcha_in_scope_is_the_switch_and_nothing_else():
    for running in (None, SimpleNamespace(running=False), SimpleNamespace(running=True)):
        off = make_bridge({"watcher_enabled": False})
        on = make_bridge({"watcher_enabled": True})
        off._captcha_watcher = on._captcha_watcher = running
        assert policy.captcha_in_scope(off) is False
        assert policy.captcha_in_scope(on) is True
        assert policy.solver_running(on) is bool(running is not None and running.running)


def test_has_solver_key_reads_the_store_fail_closed(isolated_config_dir):
    from app.services.captcha.service import CaptchaService
    svc = CaptchaService(str(isolated_config_dir))
    bridge = make_bridge({"watcher_enabled": True})
    assert policy.has_solver_key(bridge) is False  # no service at all
    bridge._captcha_service = lambda: svc
    assert policy.has_solver_key(bridge) is False  # service, empty store
    svc.apply_settings("abcdef1234567890", 240)
    assert policy.has_solver_key(bridge) is True
    assert policy.captcha_in_scope(make_bridge({"watcher_enabled": False})) is False  # key never widens scope


def test_out_of_scope_outcome_vocabulary():
    out = policy.out_of_scope()
    assert out.status == "out_of_scope" and out.reason == "watcher off"


# ── the five gates ──

async def test_check_security_does_not_probe_when_off():
    ctrl = CountingCtrl()
    ctx = make_ctx(make_bridge({"watcher_enabled": False}, pool_with_tab()), ctrl)
    assert await sjr.check_security(ctx) is False
    assert ctrl.calls == []


async def test_handle_security_block_reports_skipped_when_off():
    ctrl = CountingCtrl()
    bridge = make_bridge({"watcher_enabled": False}, pool_with_tab())
    await sjr._handle_security(make_ctx(bridge, ctrl), "CHECK_SECURITY")
    assert bridge._events == [("CHECK_SECURITY", "success", "Skipped (Watcher off)")]
    assert ctrl.calls == []


async def test_handle_captcha_returns_out_of_scope_when_off(isolated_config_dir):
    from app.services.captcha.service import CaptchaService
    svc = CaptchaService(str(isolated_config_dir))
    pool = pool_with_tab()
    bridge = make_bridge({"watcher_enabled": False}, pool)
    bridge._captcha_service = lambda: svc
    ctrl = CountingCtrl()
    outcome = await handle_captcha(CaptchaCtx(ctrl=ctrl, pool=pool, bridge=bridge, tab_id="t1"))
    assert outcome.status == "out_of_scope" and outcome.reason == "watcher off"
    assert ctrl.calls == []
    assert svc.stats.to_dict()["detected_total"] == 0
    assert pool.get_page("t1").pending_penalty == 0
    assert pool.get_page("t1").status == PageStatus.BUSY  # never marked waiting
    assert not any("🛡" in m for m, _ in bridge._logs)


async def test_settler_is_not_installed_when_off(monkeypatch):
    seen = {}

    async def fake_poll(ctx, timeout_ms):
        seen["during"] = hasattr(ctx.ctrl, "security_settler")
        return "failed", {"error": "Timeout after 1ms"}, None

    monkeypatch.setattr(sjr, "_poll_generation", fake_poll)
    ctrl = CountingCtrl()
    ctx = make_ctx(make_bridge({"watcher_enabled": False}, pool_with_tab()), ctrl)
    src, data, err = await sjr.wait_for_output(ctx, 1)
    assert seen["during"] is False and not hasattr(ctrl, "security_settler")
    assert (src, data) == (None, None) and "Timeout" in err  # normal timeout path still runs
    assert "detect" not in ctrl.calls and "visible" not in ctrl.calls


async def test_settler_is_installed_when_on(monkeypatch):
    """Positive control for the previous test: ON installs the settler as before."""
    seen = {}

    async def fake_poll(ctx, timeout_ms):
        seen["during"] = callable(getattr(ctx.ctrl, "security_settler", None))
        return "failed", {"error": "Timeout after 1ms"}, None

    monkeypatch.setattr(sjr, "_poll_generation", fake_poll)
    ctrl = CountingCtrl()
    await sjr.wait_for_output(make_ctx(make_bridge({"watcher_enabled": True}, pool_with_tab()), ctrl), 1)
    assert seen["during"] is True and not hasattr(ctrl, "security_settler")


async def test_scope_is_evaluated_per_call():
    """Live in both directions: flipping the switch needs no restart, no cached flag."""
    pool = pool_with_tab()
    bridge = make_bridge({"watcher_enabled": False}, pool)
    ctrl = CountingCtrl(visible_seq=[True, True, False])
    ctx = make_ctx(bridge, ctrl)
    assert await sjr.check_security(ctx) is False and ctrl.calls == []
    bridge._session["watcher_enabled"] = True
    assert await sjr.check_security(ctx) is True
    assert ctrl.calls[0] == "visible" and "detect" in ctrl.calls
    bridge._session["watcher_enabled"] = False
    before = len(ctrl.calls)
    assert await sjr.check_security(ctx) is False and len(ctrl.calls) == before


def test_watcher_running_delegates_to_policy():
    class Boom:
        @property
        def running(self):
            raise RuntimeError("no")

    for watcher in (None, SimpleNamespace(running=False), SimpleNamespace(running=True), Boom()):
        bridge = make_bridge({})
        bridge._captcha_watcher = watcher
        ctx = CaptchaCtx(ctrl=None, pool=None, bridge=bridge, tab_id="t1")
        assert _watcher_running(ctx) is policy.solver_running(bridge)
    assert _watcher_running(CaptchaCtx(ctrl=None, pool=None, bridge=SimpleNamespace(), tab_id="t")) is False
