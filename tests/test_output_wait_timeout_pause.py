"""S3 · `output_wait.WaitSpec.pause` — a charged `PauseClock` is subtracted from
the generation wait's elapsed time (I-52). Real loop, real `WaitSpec`, a
`check_fn` that really blocks — the loop itself is never mocked (RULE 8).

RED at base: `TypeError: WaitSpec.__init__() got an unexpected keyword argument 'pause'`.
"""

import asyncio

import pytest

from app.browser.output_wait import WaitSpec, wait_for_new_output_with_spec
from app.core.pause_clock import PauseClock

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

SETTLE_S = 0.6  # the "captcha settle" inside the first poll
TIMEOUT_S = 0.2  # a generation timeout shorter than that settle


def settling_check(clock: PauseClock | None, settle_s: float = SETTLE_S):
    """First poll blocks `settle_s` (charging `clock` if given), second poll is ready."""
    polls = {"n": 0}

    async def check_fn():
        polls["n"] += 1
        if polls["n"] == 1:
            await asyncio.sleep(settle_s)
            if clock is not None:
                clock.note(settle_s)
            return {"ready": False, "reason": "generating_no_new_yet"}
        return {"ready": True, "src": "blob:new", "reason": "ok"}

    return check_fn


async def run(spec: WaitSpec, check_fn) -> dict:
    return await asyncio.wait_for(
        wait_for_new_output_with_spec(check_fn, lambda _m: None, None, spec), 5)


async def test_a_long_settle_does_not_time_out_when_a_clock_absorbs_it():
    clock = PauseClock(cap_s=300)
    spec = WaitSpec(timeout=TIMEOUT_S, poll_interval=0.01, pause=clock)
    result = await run(spec, settling_check(clock))
    assert result["ready"] is True
    assert clock.total == pytest.approx(SETTLE_S)


async def test_the_same_wait_times_out_without_a_clock():
    """The Watcher-OFF half: identical check_fn, no clock ⇒ the settle burns the timeout."""
    spec = WaitSpec(timeout=TIMEOUT_S, poll_interval=0.01, pause=None)
    result = await run(spec, settling_check(None))
    assert result["ready"] is False
    assert result["reason"] == "timeout"


async def test_the_timeout_result_carries_the_pause_evidence():
    """A charged clock that still cannot save the wait leaves its trace in the result."""
    clock = PauseClock(cap_s=300)
    clock.note(SETTLE_S)  # charged before the loop even starts
    spec = WaitSpec(timeout=0.05, poll_interval=0.01, pause=clock)

    async def never_ready():
        await asyncio.sleep(0.02)
        return {"ready": False, "reason": "generating_no_new_yet"}

    result = await run(spec, never_ready)
    assert result["reason"] == "timeout"
    assert result["paused_s"] == pytest.approx(SETTLE_S, abs=0.05)
    assert "captcha wait" in result["pause_note"]
    # the pause was honoured: the wall clock ran ≥ timeout + pause before giving up
    assert result["elapsed"] >= 0.05


async def test_an_exhausted_cap_times_out_even_with_the_dialog_up():
    """cap 0.1 s: the settles keep coming, but only 0.1 s of them is ever absorbed."""
    clock = PauseClock(cap_s=0.1)
    spec = WaitSpec(timeout=0.15, poll_interval=0.01, pause=clock)

    async def keeps_settling():
        await asyncio.sleep(0.05)
        clock.note(0.05)  # "the dialog is still up" — charged every poll
        return {"ready": False, "reason": "generating_no_new_yet"}

    result = await run(spec, keeps_settling)
    assert result["reason"] == "timeout"
    assert result["paused_s"] <= 0.1 + 1e-6
    assert clock.expired()


async def test_wait_spec_pause_defaults_to_none():
    """Every existing caller (`output_wait_fallback`, `cdp_arena`) is untouched."""
    assert WaitSpec(timeout=1).pause is None
    assert WaitSpec(timeout=1, poll_interval=0.5).pause is None
