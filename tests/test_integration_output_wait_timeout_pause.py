# Integration/contract lane: real collaborators; not counted as function units.
"""S3 — D-13/D-14R: the generation wait honours the pause clock.

Real `wait_for_new_output_with_spec` + real `WaitSpec` (RULE 8 — the loop is
never mocked); only the 3 s re-check delay is de-fanged for runtime, and the
settle's wall time is a real `asyncio.sleep` inside `check_fn`.

RED at base: `WaitSpec(...)` has no `pause` field (TypeError). Test 10 is the
Watcher-OFF equivalence: once the field exists it passes with `pause=None`
untouched behaviour — proof the pause is the ONLY change.
"""

import asyncio


from app.browser.output_wait import WaitSpec, wait_for_new_output_with_spec

import pytest

pytestmark = pytest.mark.integration


NOT_READY = {"ready": False, "reason": "generating_no_new_yet"}
READY = {"ready": True, "src": "https://x/new.png", "associatedJobId": "j1",
         "expectedJobId": "j1"}


@pytest.fixture
def quick_recheck(monkeypatch):
    """The real 3 s finalize delay without the 3 s (timing shim, not the loop)."""
    import app.browser.output_wait_fallback as owf
    from app.browser.output_state import flatten_diagnostics

    async def _recheck(check_fn, log_cb):
        rd = flatten_diagnostics(await check_fn())
        return rd if rd.get("ready") else None

    monkeypatch.setattr(owf, "_recheck_after_delay", _recheck)


def _make_check_fn(clock, settle_s):
    calls = {"n": 0}

    async def check_fn():
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(settle_s)  # the settle blocks the poll (real time)
            if clock is not None:
                clock.note(settle_s)       # ...and the browser layer charges it
            return dict(NOT_READY)
        return dict(READY)

    return check_fn


async def test_a_long_settle_does_not_time_out_when_a_clock_absorbs_it(quick_recheck):
    from app.core.pause_clock import PauseClock
    clock = PauseClock(cap_s=300)
    spec = WaitSpec(timeout=0.2, poll_interval=0.05, pause=clock)
    result = await asyncio.wait_for(
        wait_for_new_output_with_spec(_make_check_fn(clock, 0.6), lambda m: None, None, spec),
        timeout=10)
    assert result.get("ready") is True  # the 0.6 s settle was absorbed


async def test_the_same_wait_times_out_without_a_clock(quick_recheck):
    spec = WaitSpec(timeout=0.2, poll_interval=0.05, pause=None)
    result = await asyncio.wait_for(
        wait_for_new_output_with_spec(_make_check_fn(None, 0.6), lambda m: None, None, spec),
        timeout=10)
    assert result.get("reason") == "timeout"  # Watcher-OFF equivalence


async def test_the_timeout_result_carries_the_pause_evidence(quick_recheck):
    from app.core.pause_clock import PauseClock
    clock = PauseClock(cap_s=300)
    calls = {"n": 0}

    async def never_ready():
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(0.6)
            clock.note(0.6)
        return dict(NOT_READY)

    spec = WaitSpec(timeout=0.15, poll_interval=0.05, pause=clock)
    result = await asyncio.wait_for(
        wait_for_new_output_with_spec(never_ready, lambda m: None, None, spec), timeout=10)
    assert result.get("reason") == "timeout"
    assert result["paused_s"] == pytest.approx(0.6, abs=0.05)
    assert "captcha wait" in result["pause_note"]


async def test_an_exhausted_cap_times_out_even_with_the_dialog_up(quick_recheck):
    from app.core.pause_clock import PauseClock
    clock = PauseClock(cap_s=0.1)

    async def settle_forever():
        clock.note(5.0)  # only 0.1 s of it may be absorbed
        return dict(NOT_READY)

    spec = WaitSpec(timeout=0.2, poll_interval=0.02, pause=clock)
    result = await asyncio.wait_for(
        wait_for_new_output_with_spec(settle_forever, lambda m: None, None, spec), timeout=10)
    assert result.get("reason") == "timeout"
    assert result["paused_s"] <= 0.1 + 0.05  # the cap bounds the absorption


def test_wait_spec_pause_defaults_to_none():
    assert WaitSpec(timeout=1).pause is None  # every existing caller untouched
