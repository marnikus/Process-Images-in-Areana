"""The generation timeout pauses while a captcha is being waited on (S3, D-13/D-14R).

Real `wait_for_new_output_with_spec`, real `WaitSpec`, a `check_fn` that
really blocks — the loop itself is never mocked (RULE 8). The clock rides on
`WaitSpec.pause` (D-25: the only legal carrier in output_wait.py) and is
charged by the browser layer's `_settle_timed` around the settler only.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser import output_wait
from app.browser.cdp_arena import output as arena_output
from app.browser.cdp_arena import state as arena_state
from app.browser.output_wait import WaitSpec, wait_for_new_output_with_spec
from app.core.pause_clock import PauseClock

pytestmark = pytest.mark.unit

NOT_READY = {"ready": False, "reason": "generating_no_new_yet"}


def _quiet(_msg):
    return None


async def _no_recheck(_check_fn, _log_cb):
    return None  # the 3 s finalize re-check is not the seam under test


def _settling_check(clock: PauseClock, settle_s: float, then_ready: bool):
    """A check_fn whose first poll settles a dialog for `settle_s` (charged to `clock`)."""
    polls = {"n": 0}

    async def check_fn():
        polls["n"] += 1
        if polls["n"] == 1:
            await asyncio.sleep(settle_s)
            if clock is not None:
                clock.note(settle_s)
        if then_ready and polls["n"] > 1:
            return {"ready": True, "src": "blob:new", "reason": "ready"}
        return dict(NOT_READY)

    return check_fn


async def test_a_long_settle_does_not_time_out_when_a_clock_absorbs_it(monkeypatch):
    monkeypatch.setattr(output_wait, "_recheck_after_delay", _no_recheck)
    clock = PauseClock()
    spec = WaitSpec(timeout=0.2, poll_interval=0.01, pause=clock)
    result = await wait_for_new_output_with_spec(_settling_check(clock, 0.6, True), _quiet, None, spec)
    assert result["ready"] is True
    assert clock.total == pytest.approx(0.6)


async def test_the_same_wait_times_out_without_a_clock(monkeypatch):
    """Equivalence: the Watcher-OFF half — no clock, the 0.6 s settle burns the 0.2 s timeout."""
    monkeypatch.setattr(output_wait, "_recheck_after_delay", _no_recheck)
    spec = WaitSpec(timeout=0.2, poll_interval=0.01)
    result = await wait_for_new_output_with_spec(_settling_check(None, 0.6, True), _quiet, None, spec)
    assert result["reason"] == "timeout"
    assert "paused_s" not in result and "pause_note" not in result


async def test_the_timeout_result_carries_the_pause_evidence():
    clock = PauseClock()
    spec = WaitSpec(timeout=0.2, poll_interval=0.01, pause=clock)
    result = await wait_for_new_output_with_spec(_settling_check(clock, 0.6, False), _quiet, None, spec)
    assert result["reason"] == "timeout"
    assert result["paused_s"] == pytest.approx(0.6, abs=0.05)
    assert "captcha wait" in result["pause_note"]
    assert result["elapsed"] == pytest.approx(0.2, abs=0.15)  # real time minus the pause


async def test_an_exhausted_cap_times_out_even_with_the_dialog_up():
    """The cap ends the wait on its own: a 5 s timeout, a 0.1 s pause budget, a dialog that never clears."""
    clock = PauseClock(cap_s=0.1)

    async def keeps_settling():
        await asyncio.sleep(0.03)
        clock.note(0.03)
        return dict(NOT_READY)

    spec = WaitSpec(timeout=5.0, poll_interval=0.001, pause=clock)
    result = await asyncio.wait_for(
        wait_for_new_output_with_spec(keeps_settling, _quiet, None, spec), timeout=2.0)
    assert result["reason"] == "timeout"
    assert result["paused_s"] <= 0.1 + 1e-6
    assert clock.expired() is True


def test_wait_spec_pause_defaults_to_none():
    assert WaitSpec(timeout=1).pause is None  # every existing caller is untouched


# --- cdp_arena/output.py: the charge happens around the settler only ---------------

def _dialog(visible: bool, monkeypatch):
    async def fake_visible(_cdp):
        return visible

    monkeypatch.setattr(arena_state, "is_security_dialog_visible", fake_visible)


async def test_security_gate_charges_the_ctrl_clock_around_the_settle(monkeypatch):
    _dialog(True, monkeypatch)
    ctrl = SimpleNamespace(pause_clock=PauseClock(cap_s=300))

    async def settler():
        await asyncio.sleep(0.05)

    ctrl.security_settler = settler
    await arena_output._security_gate(cdp=None, ctrl=ctrl)
    assert 0.04 <= ctrl.pause_clock.total <= 0.5

    _dialog(False, monkeypatch)
    before = ctrl.pause_clock.total
    await arena_output._security_gate(cdp=None, ctrl=ctrl)
    assert ctrl.pause_clock.total == before  # no dialog ⇒ no settle ⇒ no charge


async def test_a_failing_settle_is_still_charged_and_never_raises(monkeypatch):
    _dialog(True, monkeypatch)
    ctrl = SimpleNamespace(pause_clock=PauseClock(cap_s=300))

    async def settler():
        await asyncio.sleep(0.02)
        raise RuntimeError("captcha wait hit the cap")

    ctrl.security_settler = settler
    await arena_output._security_gate(cdp=None, ctrl=ctrl)  # swallowed, as before
    assert ctrl.pause_clock.total >= 0.015

    bare = SimpleNamespace(security_settler=settler)  # Watcher OFF shape: no clock at all
    await arena_output._security_gate(cdp=None, ctrl=bare)


async def test_timeout_text_quotes_the_pause_note(monkeypatch):
    async def fake_baseline(_cdp):
        return {"output_count": 0}

    monkeypatch.setattr(arena_output, "capture_baseline", fake_baseline)
    clock = PauseClock(cap_s=300)
    clock.note(12)
    paused = {"ready": False, "reason": "timeout", "paused_s": 12.0, "pause_note": clock.describe()}
    status, data = await arena_output._map_wait_result(None, paused, {}, 180000)
    assert status == "failed"
    assert data["error"] == "Timeout after 180000ms (+12s captcha wait (cap 300s, 288s left))"
    assert data["paused_s"] == 12.0

    status, plain = await arena_output._map_wait_result(None, {"ready": False, "reason": "timeout"}, {}, 180000)
    assert plain["error"] == "Timeout after 180000ms"  # unchanged wording when nothing was paused
    assert plain["paused_s"] == 0
