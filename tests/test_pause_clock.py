"""S3 — the pause clock: exact, capped at the one knob, and cannot hide a timeout."""

import time

import pytest

from app.core.pause_clock import PauseClock


@pytest.mark.unit
def test_note_accumulates_and_ignores_garbage():
    clock = PauseClock(cap_s=100)
    clock.note(1.5)
    clock.note(2.5)
    clock.note(0)
    clock.note(-3)
    clock.note(float("nan"))
    clock.note(None)
    assert clock.total == 4.0


@pytest.mark.unit
def test_a_second_settle_in_the_same_wait_adds_nothing_past_the_cap():
    """R22's lock: the cap is cumulative per wait, not per settle."""
    clock = PauseClock(cap_s=10)
    clock.note(6)
    clock.note(6)
    assert clock.total == 10                       # absorbs 4, not 6
    assert clock.expired() is True
    assert clock.remaining() == 0


@pytest.mark.unit
def test_uncapped_clock_never_expires():
    """No cap installed ⇔ Watcher OFF ⇔ the timeout burns real time."""
    clock = PauseClock()
    clock.note(10_000)
    assert clock.expired() is False
    assert clock.remaining() > 10_000


@pytest.mark.unit
def test_paused_elapsed_subtracts_and_floors_at_zero():
    clock = PauseClock(cap_s=300, total=12)
    assert clock.paused_elapsed(start=100, now=130) == 18
    clock.total = 40
    assert clock.paused_elapsed(start=100, now=130) == 0


@pytest.mark.unit
def test_paused_elapsed_defaults_to_now():
    start = time.monotonic() - 50
    clock = PauseClock(cap_s=60, total=30)
    first = clock.paused_elapsed(start)
    second = clock.paused_elapsed(start)
    assert 19.9 < first < 21
    assert second >= first > 0


@pytest.mark.unit
def test_describe_names_absorbed_cap_and_remaining():
    assert PauseClock(cap_s=300, total=12).describe() == "+12s captcha wait (cap 300s, 288s left)"
    assert PauseClock(cap_s=300).describe() == ""   # nothing absorbed: silent


@pytest.mark.unit
def test_remaining_is_never_negative():
    clock = PauseClock(cap_s=1)
    clock.note(50)
    assert clock.remaining() == 0


@pytest.mark.unit
def test_the_clock_is_not_shared_between_waits():
    """The per-generation-wait rule: every wait starts a fresh accumulator."""
    first, second = PauseClock(cap_s=10), PauseClock(cap_s=10)
    first.note(10)
    assert first.expired() is True
    assert second.expired() is False
    assert second.total == 0
