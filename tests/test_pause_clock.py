"""PauseClock — the seconds a generation wait spent inside a captcha wait (S3, D-13/D-14R/D-25).

Pure value object, no fakes: the browser layer charges it (`note`), the wait
loop reads it (`paused_elapsed`, `expired`), the timeout text quotes it
(`describe`). One clock per generation wait; the cap is cumulative (R22).
"""

import time

import pytest

from app.core.pause_clock import PauseClock

pytestmark = pytest.mark.unit


def test_note_accumulates_and_ignores_garbage():
    clock = PauseClock()
    clock.note(1.5)
    clock.note(2.5)
    assert clock.total == 4.0
    for garbage in (0, -3, float("nan"), float("inf"), None, "soon"):
        clock.note(garbage)  # never raises, never charges
    assert clock.total == 4.0


def test_cap_is_cumulative_per_wait():
    """R22: a second settle in the same wait absorbs only what the cap leaves."""
    clock = PauseClock(cap_s=10)
    clock.note(6)
    assert clock.expired() is False and clock.remaining() == 4
    clock.note(6)
    assert clock.total == 10          # absorbed 4, not 6
    assert clock.expired() is True
    clock.note(6)
    assert clock.total == 10          # exhausted: charges nothing more


def test_uncapped_clock_never_expires():
    clock = PauseClock()              # cap_s=0 ⇒ uncapped
    clock.note(10_000)
    assert clock.expired() is False
    assert clock.remaining() > 10_000
    assert PauseClock(cap_s=-5).expired() is False  # a negative cap is "no cap"


def test_paused_elapsed_subtracts_and_floors_at_zero():
    clock = PauseClock()
    clock.note(12)
    assert clock.paused_elapsed(start=100, now=130) == 18
    clock.note(28)                    # total 40 > the 30 s span
    assert clock.paused_elapsed(start=100, now=130) == 0


def test_paused_elapsed_defaults_to_now():
    clock = PauseClock()
    start = time.monotonic()
    first = clock.paused_elapsed(start)
    second = clock.paused_elapsed(start)
    assert 0 <= first <= second


def test_describe_names_absorbed_and_cap():
    clock = PauseClock(cap_s=300)
    assert clock.describe() == ""     # nothing absorbed ⇒ nothing to say
    clock.note(12)
    text = clock.describe()
    assert "+12s captcha wait" in text and "cap 300s" in text and "288s left" in text
    uncapped = PauseClock()
    uncapped.note(7)
    assert uncapped.describe() == "+7s captcha wait"  # no cap ⇒ no budget wording


def test_remaining_never_negative():
    clock = PauseClock(cap_s=5)
    clock.note(100)
    assert clock.remaining() == 0
    assert clock.total == 5


def test_clock_is_not_shared_between_waits():
    a, b = PauseClock(cap_s=30), PauseClock(cap_s=30)
    a.note(20)
    assert b.total == 0 and b.remaining() == 30
    assert a.remaining() == 10
