"""The generation wait stops burning its timeout while a captcha settles (S3).

RULE 8: the real `wait_for_new_output_with_spec` loop with a real `WaitSpec`;
the `check_fn` blocks with a real (sync) sleep and charges a real clock, the way
`cdp_arena._settle_timed` charges it in production. `asyncio.sleep` is patched
(the loop's 3 s re-check), `time.sleep` is real (the settle being absorbed).
"""

import asyncio
import time

import pytest

from app.browser.cdp_arena.output import _settle_timed, _timeout_text
from app.browser.output_wait import WaitSpec, wait_for_new_output_with_spec
from app.core.pause_clock import PauseClock


def instant_sleep(monkeypatch):
    async def fake_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)


def make_settling_check(clock, settle_s, charge_s):
    """First poll absorbs a long settle, later polls are ready."""
    calls = []

    async def check_fn():
        calls.append(1)
        if len(calls) == 1:
            time.sleep(settle_s)
            clock.note(charge_s)
            return {"ready": False, "reason": "generating"}
        return {"ready": True, "src": "https://x/new.png"}

    return check_fn


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_long_settle_does_not_time_out_when_a_clock_absorbs_it(monkeypatch):
    instant_sleep(monkeypatch)
    clock = PauseClock(cap_s=300)
    spec = WaitSpec(timeout=0.2, poll_interval=0.01, pause=clock)
    result = await wait_for_new_output_with_spec(
        make_settling_check(clock, 0.6, 0.6), lambda m: None, None, spec)
    assert result["ready"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_same_wait_times_out_without_a_clock(monkeypatch):
    instant_sleep(monkeypatch)
    clock = PauseClock(cap_s=300)
    spec = WaitSpec(timeout=0.2, poll_interval=0.01, pause=None)
    result = await wait_for_new_output_with_spec(
        make_settling_check(clock, 0.6, 0.6), lambda m: None, None, spec)
    assert result["reason"] == "timeout"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_timeout_result_carries_the_pause_evidence(monkeypatch):
    instant_sleep(monkeypatch)
    clock = PauseClock(cap_s=300)

    async def never_ready():
        time.sleep(0.8)
        clock.note(0.6)
        return {"ready": False, "reason": "generating"}

    spec = WaitSpec(timeout=0.1, poll_interval=0.01, pause=clock)
    result = await wait_for_new_output_with_spec(never_ready, lambda m: None, None, spec)
    assert result["reason"] == "timeout"
    assert result["paused_s"] == pytest.approx(0.6, abs=0.05)
    assert "captcha wait" in result["pause_note"]
    # The cdp_arena timeout text carries the same evidence (both arms pinned).
    assert _timeout_text(result, 100) == f"Timeout after 100ms ({result['pause_note']})"
    assert _timeout_text({"reason": "timeout"}, 100) == "Timeout after 100ms"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_an_exhausted_cap_times_out_even_with_the_dialog_up(monkeypatch):
    instant_sleep(monkeypatch)
    clock = PauseClock(cap_s=0.1)

    async def settle():
        time.sleep(0.05)

    async def keep_settling():
        await _settle_timed(settle, clock)
        return {"ready": False, "reason": "generating"}

    spec = WaitSpec(timeout=0.05, poll_interval=0.01, pause=clock)
    result = await wait_for_new_output_with_spec(keep_settling, lambda m: None, None, spec)
    assert result["reason"] == "timeout"
    assert result["paused_s"] <= 0.1 + 1e-9


@pytest.mark.unit
def test_wait_spec_pause_defaults_to_none():
    assert WaitSpec(timeout=1).pause is None
