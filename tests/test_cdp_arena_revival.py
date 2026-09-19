"""Dead-generation toast revival at the output-wait boundary (RULE 8).

The captcha-blocked request dies server-side and the site toasts
'Something went wrong while generating the response. Please try again.'
The wait must hand that poll to the armed revival policy ONCE instead of
aborting the job — every other error still aborts (RULE 4, fail honest).
Design: docs/archive/2026-09-18-dead-generation-toast-revival/design.md
"""

import pytest

from app.browser.cdp_arena import (CDPArenaController, _convert_dead_generation,
                                   _poll_diag_or_revive)
from app.browser.cdp_arena.output import PollContext
from app.utils.page_errors import PageErrorAbort

DEAD = ("Page error: Something went wrong while generating the response. "
        "Please try again.")
LIMIT = "Page error: You have reached your daily limit"


class ScanCtrl:
    """Minimal ctrl double: error-corpus scan + attribute surface."""

    def __init__(self, corpus_after=""):
        self._corpus_after = corpus_after
        self.scans = 0

    async def _scan_page_errors(self):
        self.scans += 1
        return self._corpus_after


async def _gate(diag):
    return diag


@pytest.mark.unit
@pytest.mark.asyncio
async def test_convert_non_dead_error_is_none():
    ctrl = ScanCtrl()
    ctrl.resume_gate = _gate
    assert await _convert_dead_generation(ctrl, LIMIT) is None
    assert ctrl.scans == 0  # nothing re-baselined for terminal errors
    assert not getattr(ctrl, "_dead_gen_revived", False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_convert_requires_armed_gate():
    ctrl = ScanCtrl()  # no resume_gate attribute
    assert await _convert_dead_generation(ctrl, DEAD) is None
    assert not getattr(ctrl, "_dead_gen_revived", False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_convert_dead_error_once_and_rebaselines():
    ctrl = ScanCtrl(corpus_after="Something went wrong while generating the response.")
    ctrl.resume_gate = _gate
    ctrl._err_base = ""
    diag = await _convert_dead_generation(ctrl, DEAD)
    assert diag == {"ready": False, "reason": "dead_generation",
                    "dead_generation_error": DEAD}
    assert ctrl._dead_gen_revived is True
    assert ctrl._err_base  # lingering toast absorbed into the baseline
    assert await _convert_dead_generation(ctrl, DEAD) is None  # one-shot


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_or_revive_passthrough_and_paths():
    ctrl = ScanCtrl()
    ctrl.resume_gate = _gate

    async def ok_poll():
        return {"ready": False, "reason": "generating"}

    got = await _poll_diag_or_revive(PollCtrl(ok_poll, ctrl), PollContext())
    assert got == {"ready": False, "reason": "generating"}

    async def dead_poll():
        raise PageErrorAbort(DEAD)

    got = await _poll_diag_or_revive(PollCtrl(dead_poll, ctrl), PollContext())
    assert got["reason"] == "dead_generation"  # revived instead of aborting

    ctrl2 = ScanCtrl()  # gate gone -> same toast aborts honestly
    with pytest.raises(PageErrorAbort):
        await _poll_diag_or_revive(PollCtrl(dead_poll, ctrl2), PollContext())

    async def limit_poll():
        raise PageErrorAbort(LIMIT)

    with pytest.raises(PageErrorAbort):  # terminal errors never revive
        await _poll_diag_or_revive(PollCtrl(limit_poll, ctrl), PollContext())


class PollCtrl:
    """Binds a scripted _poll_output_diag onto a scan ctrl."""

    def __init__(self, poll_fn, scan_ctrl):
        self._poll = poll_fn
        self._scan = scan_ctrl

    async def _poll_output_diag(self, old_srcs, correlation_id, old_outputs):
        return await self._poll()

    async def _scan_page_errors(self):
        return await self._scan._scan_page_errors()

    def __getattr__(self, name):  # resume_gate / _dead_gen_revived / _err_base
        return getattr(self._scan, name)

    def __setattr__(self, name, value):
        if name in ("_poll", "_scan"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._scan, name, value)


class WaitCdp:
    """Scripted CDP for the controller-level wait test."""

    def __init__(self):
        self.corpus = ""

    async def evaluate(self, js):
        if 'role="alert"' in js:
            return self.corpus
        return None


@pytest.mark.asyncio
async def test_wait_loop_revives_dead_generation_then_completes(monkeypatch):
    """Full path: toast -> revival diag -> gate consulted -> output arrives."""
    import asyncio
    import app.browser.output_wait as ow

    async def instant(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)
    ctrl = CDPArenaController(WaitCdp())
    polls = {"n": 0}

    async def fake_poll(old_srcs, correlation_id, old_outputs):
        polls["n"] += 1
        if polls["n"] == 1:
            raise PageErrorAbort(DEAD)
        return {"ready": True, "src": "https://x/out.png", "rect": {"w": 1}}

    ctrl._poll_output_diag = fake_poll
    seen = []

    async def gate(diag):
        seen.append(diag)
        return diag

    ctrl.resume_gate = gate
    status, data = await ctrl.wait_for_new_output({"output_srcs": [], "outputs": []},
                                                  timeout_ms=10000)
    assert status == "completed" and data["new_src"] == "https://x/out.png"
    assert seen[0]["reason"] == "dead_generation"  # gate got the revival poll
    assert ctrl._dead_gen_revived is True


@pytest.mark.asyncio
async def test_wait_loop_second_toast_fails_honestly(monkeypatch):
    """One revival per wait: a toast after the resubmit aborts (RULE 4)."""
    import asyncio

    async def instant(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)
    ctrl = CDPArenaController(WaitCdp())

    async def always_dead(old_srcs, correlation_id, old_outputs):
        raise PageErrorAbort(DEAD)

    ctrl._poll_output_diag = always_dead

    async def gate(diag):
        return diag

    ctrl.resume_gate = gate
    status, data = await ctrl.wait_for_new_output({"output_srcs": [], "outputs": []},
                                                  timeout_ms=10000)
    assert status == "failed" and "Something went wrong" in data["error"]
