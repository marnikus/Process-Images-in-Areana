"""S3 — a captcha settle pauses the generation timeout; nothing else does.

RULE 8: the real `wait_for_new_output_with_spec` loop and the real `WaitSpec`
carrier; only the wall clock is faked (deterministic advance, no sleeps).
"""

import asyncio
import time

import pytest

from app.browser.output_wait import WaitSpec, wait_for_new_output_with_spec
from app.core.pause_clock import PauseClock


@pytest.fixture
def fake_time(monkeypatch):
    """One mutable clock; `check_fn` advances it to simulate work happening."""
    fake = {"now": 0.0}
    monkeypatch.setattr(time, "monotonic", lambda: fake["now"])

    async def nop_sleep(_s):
        return None

    monkeypatch.setattr(asyncio, "sleep", nop_sleep)
    return fake


NOT_READY = {"ready": False, "reason": "generating_no_new_yet"}


@pytest.mark.unit
def test_a_long_settle_does_not_time_out_when_a_clock_absorbs_it(event_loop, fake_time):
    clock = PauseClock(cap_s=300)
    spec = WaitSpec(timeout=10, poll_interval=0, pause=clock)
    polls = [0]

    async def check_fn():
        polls[0] += 1
        if polls[0] == 1:
            clock.note(60)                  # a captcha held the page for 60 s
            fake_time["now"] += 60
            return dict(NOT_READY)
        return {"ready": True, "src": "https://r2/new.png"}  # (the 3 s recheck also lands here)

    out = event_loop.run_until_complete(
        wait_for_new_output_with_spec(check_fn, lambda _m: None, None, spec))

    assert out.get("ready") is True
    assert clock.total == 60


@pytest.mark.unit
def test_the_same_wait_times_out_without_a_clock(event_loop, fake_time):
    """Positive control: identical wait, Watcher OFF (pause=None) ⇒ timeout.

    The Watcher-OFF half of the contract — green at base once the field
    exists, and the proof that the pause is the only behavioural change.
    """
    spec = WaitSpec(timeout=10, poll_interval=0)

    async def check_fn():
        fake_time["now"] += 60
        return dict(NOT_READY)

    out = event_loop.run_until_complete(
        wait_for_new_output_with_spec(check_fn, lambda _m: None, None, spec))

    assert out["ready"] is False
    assert out["reason"] == "timeout"
    assert "paused_s" not in out            # Watcher OFF: no pause vocabulary


@pytest.mark.unit
def test_the_timeout_result_carries_the_pause_evidence(event_loop, fake_time):
    """A charged clock is reported, never silent (D-13)."""
    clock = PauseClock(cap_s=300)
    spec = WaitSpec(timeout=10, poll_interval=0, pause=clock)

    async def check_fn():
        clock.note(4)
        fake_time["now"] += 40              # wall: 40 s, paused: 36 s per pass
        return dict(NOT_READY)

    out = event_loop.run_until_complete(
        wait_for_new_output_with_spec(check_fn, lambda _m: None, None, spec))

    assert out["reason"] == "timeout"
    assert out["paused_s"] == 4
    assert "captcha wait" in out["pause_note"]
    assert out["elapsed"] == 36             # 40 wall seconds minus the 4 donated ones


@pytest.mark.unit
def test_an_exhausted_cap_times_out_even_while_the_dialog_keeps_settling(event_loop, fake_time):
    """D-14R's other end: past the cap the wait gives up the free pass."""
    clock = PauseClock(cap_s=10)            # only 10 s may ever be donated
    spec = WaitSpec(timeout=20, poll_interval=0, pause=clock)

    async def check_fn():
        clock.note(60)                      # each settle claims 60 s, clock holds 10
        fake_time["now"] += 60
        return dict(NOT_READY)

    out = event_loop.run_until_complete(
        wait_for_new_output_with_spec(check_fn, lambda _m: None, None, spec))

    assert out["reason"] == "timeout"
    assert out["paused_s"] == 10


@pytest.mark.unit
def test_wait_spec_pause_defaults_to_none():
    """Every pre-S3 caller (output_wait_fallback, cdp_arena) is untouched."""
    assert WaitSpec(timeout=1).pause is None


@pytest.mark.unit
def test_loopstate_was_not_touched():
    """D-25 source lock: LoopState stays at the file's recorded span-4 datum."""
    import dataclasses

    from app.browser.output_wait import LoopState, WaitSpec

    assert {f.name for f in dataclasses.fields(LoopState)} == {"last", "spin_visible", "start"}
    assert "pause" in {f.name for f in dataclasses.fields(WaitSpec)}
