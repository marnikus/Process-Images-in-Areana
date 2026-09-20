"""Output-wait low-level helpers — direct seam covers (RULE 16 coverage ratchet).

These helpers exist behind `wait_for_new_output`'s retry loop and the panel
flow only reaches them on rare paths; the ratchet floor was recorded with
them covered, so they get their own deterministic unit covers:

* `_run_resume_gate` — no gate, gate raises (fail-open), gate answers.
* `_scan_safely` — no scanner, scanner raises (fail-open ""), happy.
* `_settle_timed` — no clock settles plain; a live clock is charged.
* `_poll_diag_or_revive` — ctrl-method dispatch, dead-gen conversion, re-raise.
* `_poll_output_diag` — ready fast-path, page-error abort, not-ready diag.

No real CDP, no sleeps (RULE 8: real production code, controllable doubles).
"""

import pytest

from app.browser.cdp_arena.output import (
    _poll_diag_or_revive,
    _poll_output_diag,
    _rebaseline_errors,
    _run_resume_gate,
    _scan_safely,
    _settle_timed,
    PollContext,
)
from app.utils.page_errors import PageErrorAbort


class FakeCtrl:
    def __init__(self, gate=None):
        self.resume_gate = gate
        self._err_base = "old"
        self.scan_calls = 0

    async def scan_page_errors(self):
        self.scan_calls += 1
        return "fresh"


def ctx():
    return PollContext(correlation_id="cid", old_outputs=[], old_srcs=[], err_base="old")


# --- _run_resume_gate ----------------------------------------------------

@pytest.mark.asyncio
async def test_resume_gate_passthrough_without_gate():
    assert await _run_resume_gate(FakeCtrl(None), {"ready": False}) == {"ready": False}


@pytest.mark.asyncio
async def test_resume_gate_fail_open_on_broken_gate():
    async def boom(_diag):
        raise RuntimeError("nope")

    out = await _run_resume_gate(FakeCtrl(boom), {"ready": True, "via": "raw"})
    assert out == {"ready": True, "via": "raw"}


@pytest.mark.asyncio
async def test_resume_gate_uses_the_gate_answer():
    async def gate(_diag):
        return {"ready": False, "reason": "revived"}

    assert (await _run_resume_gate(FakeCtrl(gate), {}))["reason"] == "revived"


# --- _scan_safely --------------------------------------------------------

@pytest.mark.asyncio
async def test_scan_safely_absent_scanner_is_empty():
    assert await _scan_safely(None) == ""


@pytest.mark.asyncio
async def test_scan_safely_broken_scanner_is_empty():
    async def boom():
        raise OSError("cdp dead")

    assert await _scan_safely(boom) == ""


@pytest.mark.asyncio
async def test_rebaseline_errors_uses_the_scanner_and_updates_both_bases():
    ctrl = FakeCtrl()
    fresh = await _rebaseline_errors(ctrl, ctx())
    assert fresh == "fresh" and ctrl._err_base == "fresh" and ctrl.scan_calls == 1


# --- _settle_timed (D-14R charging) --------------------------------------

class SpyClock:
    def __init__(self):
        self.t = 0.0
        self.charged = 0.0

    def monotonic(self):
        return self.t

    def note(self, dur):
        self.charged += dur


@pytest.mark.asyncio
async def test_settle_timed_without_clock_just_settles():
    done = []

    async def settle():
        done.append("s")

    await _settle_timed(settle, None)
    assert done == ["s"]


@pytest.mark.asyncio
async def test_settle_timed_charges_the_wall_time(monkeypatch):
    t = [10.0]
    monkeypatch.setattr("time.monotonic", lambda: t[0])

    async def settle():
        t[0] += 2.5

    clock = SpyClock()
    await _settle_timed(settle, clock)
    assert clock.charged == 2.5


# --- _poll_diag_or_revive ------------------------------------------------

@pytest.mark.asyncio
async def test_poll_diag_prefers_the_ctrl_method():
    class MethodCtrl(FakeCtrl):
        async def _poll_output_diag(self, old_srcs, cid, old_outputs):
            return {"ready": True, "via": (cid, len(old_outputs))}

    out = await _poll_diag_or_revive(MethodCtrl(), ctx())
    assert out["ready"] is True and out["via"] == ("cid", 0)


@pytest.mark.asyncio
async def test_poll_diag_reraises_a_non_arena_page_error():
    async def poll(*_a):
        raise PageErrorAbort("Something went wrong entirely")

    class MethodCtrl(FakeCtrl):
        _poll_output_diag = staticmethod(poll)

    with pytest.raises(PageErrorAbort):
        await _poll_diag_or_revive(MethodCtrl(), ctx())


# --- _poll_output_diag ---------------------------------------------------

class FakeCdp:
    def __init__(self, value, scan=""):
        self.value = value
        self.scan = scan

    async def evaluate(self, _js):
        return self.value

    async def scan_page_errors(self):
        return self.scan


@pytest.mark.asyncio
async def test_poll_output_diag_ready_fast_path():
    diag = await _poll_output_diag(FakeCdp({"ok": True, "ready": True}), ctx(), FakeCtrl())
    assert diag["ready"] is True


@pytest.mark.asyncio
async def test_poll_output_diag_abort_on_fresh_page_error(monkeypatch):
    monkeypatch.setattr("app.browser.cdp_arena.output.match_page_error", lambda raw, base: "OOM")
    with pytest.raises(PageErrorAbort, match="OOM"):
        await _poll_output_diag(FakeCdp(None), ctx(), FakeCtrl())


@pytest.mark.asyncio
async def test_poll_output_diag_returns_not_ready_diagnostic():
    diag = await _poll_output_diag(FakeCdp(None), ctx(), FakeCtrl())
    assert diag == {"ready": False, "reason": "no_result"}
