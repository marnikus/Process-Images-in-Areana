# Integration/contract lane: real collaborators; not counted as function units.
"""S2 — Captcha scope: one predicate owns "is captcha work allowed now?".

RED-first (tdd-interfaces.md §S2). Watcher OFF ⇒ no probe, no overlay,
no `waiting_captcha` mark, no stats/recording/penalty, no `🛡` line
(D-23). Tests 1-2 fail at base with ImportError (policy.py does not
exist); tests 3-8 fail at base on BEHAVIOUR (the gates probe/wait
unconditionally). Rule: a test may not double the seam it tests (D-27),
so hosts carry the real config/pool shape, never a scope flag of their own.
"""

import asyncio
import json
from types import SimpleNamespace


from app.services import single_job_runner as sjr
from app.services.captcha.service import CaptchaCtx, handle_captcha

import pytest

pytestmark = pytest.mark.integration


def make_scope_bridge(session=None, **extra):
    """Bridge duck-type with a dict-backed session (switch defaults OFF)."""
    state = {"watcher_captcha_timeout_sec": 300}
    if session:
        state.update(session)
    logs = []
    bridge = SimpleNamespace(
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: None,
        _state=state,
        _logs=logs,
        **extra,
    )
    return bridge


def make_counting_ctrl(visible_seq=(), detect_visible=True):
    """CDP double: every probe and dialog poll is counted."""
    seq = list(visible_seq)
    ctrl = SimpleNamespace()
    ctrl.visible_calls = []
    ctrl.probes = []
    ctrl.overlay_calls = []

    async def visible():
        ctrl.visible_calls.append("visible")
        return seq.pop(0) if seq else False

    async def evaluate(js):
        ctrl.probes.append(js)
        return json.dumps({"visible": detect_visible, "kind": "recaptcha_v2",
                           "sitekey": "sk", "url": "https://arena.ai"})

    async def overlay(*a, **k):
        ctrl.overlay_calls.append(k)
        return True

    async def hide():
        return True

    ctrl.is_security_dialog_visible = visible
    ctrl.cdp = SimpleNamespace(evaluate=evaluate)
    ctrl.show_watcher_overlay = overlay
    ctrl.hide_watcher_overlay = hide
    return ctrl


def make_sjr_ctx(bridge, ctrl, tab_id="t1"):
    return sjr.JobCtx(bridge=bridge, ctrl=ctrl, client=None, tab_id=tab_id,
                      img=SimpleNamespace(absolute_path="/tmp/i.png", relative_path="i.png",
                                          status="pending", output_path=None, error=None),
                      urls=[], job_id="j1", corr_id="c1",
                      final_prompt="p [JOB-ID: c1]",
                      baseline={"output_count": 0, "output_srcs": []})


def make_captcha_ctx(bridge, ctrl, logs, tab_id="t1"):
    return CaptchaCtx(ctrl=ctrl, pool=None, bridge=bridge, tab_id=tab_id,
                      source="check-security", log=lambda m, l="info": logs.append(m))


def instant_sleep(monkeypatch):
    async def _fast(_s):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast)


# ── 1-2 · the policy predicate itself ──


# ── 3-4 · the runner's security gates ──

async def test_check_security_does_not_probe_when_off():
    bridge = make_scope_bridge()
    ctrl = make_counting_ctrl([False])
    assert await sjr.check_security(make_sjr_ctx(bridge, ctrl)) is False
    assert ctrl.visible_calls == []  # OFF ⇒ not even a look (D-23)


async def test_handle_security_block_reports_skipped_when_off():
    """RULE 9: skipping is success — the block must not claim a dialog it never sought."""
    bridge = make_scope_bridge()
    events = []
    bridge._emit_job_action_status = lambda a: events.append(
        (getattr(a.block, "block_id", a.block), a.status, a.message))
    ctrl = make_counting_ctrl()
    await sjr._handle_security(make_sjr_ctx(bridge, ctrl),
                               SimpleNamespace(block_id="CHECK_SECURITY"))
    assert events == [("CHECK_SECURITY", "success", "Skipped (Watcher off)")]
    assert ctrl.visible_calls == []


# ── 5 · the choke point ──

async def test_handle_captcha_returns_out_of_scope_when_off(monkeypatch):
    instant_sleep(monkeypatch)
    bridge = make_scope_bridge()
    logs = []
    ctrl = make_counting_ctrl([True, False])
    outcome = await handle_captcha(make_captcha_ctx(bridge, ctrl, logs))
    assert (outcome.status, outcome.reason) == ("out_of_scope", "watcher off")
    assert ctrl.probes == [] and ctrl.visible_calls == [] and ctrl.overlay_calls == []


# ── 6 · the settler inside the generation wait ──

async def test_settler_installation_follows_the_scope(monkeypatch):
    """OFF ⇒ never installed; ON ⇒ installed for the wait (positive control)."""
    seen = {}

    async def poll(ctx, timeout_ms):
        seen["during"] = getattr(ctx.ctrl, "security_settler", None)
        return "completed", {"new_src": "https://x/n.png"}

    async def verified(ctx, src):
        return "completed", {}, src

    async def noop(ctx, *a):
        return None

    monkeypatch.setattr(sjr, "_poll_generation", poll)
    monkeypatch.setattr(sjr, "_verify_download", verified)
    monkeypatch.setattr(sjr, "_show_gen_overlay", noop)
    monkeypatch.setattr(sjr, "_arm_revival", lambda ctx, *a: None)
    monkeypatch.setattr(sjr, "_clear_revival", lambda ctx, *a: None)
    for on, want in ((False, None), (True, "installed")):
        bridge = make_scope_bridge({"watcher_enabled": on})
        ctx = make_sjr_ctx(bridge, make_counting_ctrl())
        await sjr.wait_for_output(ctx, 1000)
        if want is None:
            assert seen["during"] is None
        else:
            assert callable(seen["during"])
        assert not hasattr(ctx.ctrl, "security_settler")  # cleaned up either way


# ── 7 · the scope is read per call, not cached ──

async def test_scope_is_evaluated_per_call():
    bridge = make_scope_bridge()
    ctrl = make_counting_ctrl([False, False])
    ctx = make_sjr_ctx(bridge, ctrl)
    await sjr.check_security(ctx)
    assert ctrl.visible_calls == []  # OFF ⇒ no probe
    bridge._state["watcher_enabled"] = True
    await sjr.check_security(ctx)
    assert ctrl.visible_calls == ["visible"]  # flipped ON ⇒ probes at once, no restart


# ── 8 · one owner for the watcher-running question ──

def test_watcher_running_delegates_to_policy():
    from app.services.captcha import policy
    from app.services.captcha.service import _watcher_running
    shapes = (None, SimpleNamespace(running=False), SimpleNamespace(running=True))
    for watcher in shapes:
        bridge = make_scope_bridge()
        if watcher is not None:
            bridge._captcha_watcher = watcher
        ctx = make_captcha_ctx(bridge, make_counting_ctrl(), [])
        assert _watcher_running(ctx) == policy.solver_running(bridge)
    class AngryWatcher:
        @property
        def running(self):
            raise RuntimeError("watcher state unreadable")

    angry = make_scope_bridge()
    angry._captcha_watcher = AngryWatcher()
    assert policy.solver_running(angry) is False  # fail closed
