"""S3 · `app/core/pause_clock.PauseClock` — the value object the browser layer
charges and the wait loop reads (I-52: the generation timeout is paused during
a captcha wait, and the pause is capped per generation wait).

Pure value object: no fakes, no I/O. RED at base: `ModuleNotFoundError`.
"""

import math
import time

import pytest

from app.core.pause_clock import PauseClock

pytestmark = pytest.mark.unit


def test_note_accumulates_and_ignores_garbage():
    clock = PauseClock(cap_s=300)
    clock.note(1.5)
    clock.note(2.5)
    assert clock.total == 4.0
    for garbage in (0, -3, float("nan"), None, "x"):
        clock.note(garbage)  # never raises
    assert clock.total == 4.0


def test_cap_is_cumulative_per_wait():
    """R22: a second settle in the same wait absorbs only what is left of the cap."""
    clock = PauseClock(cap_s=10)
    clock.note(6)
    assert clock.total == 6 and not clock.expired()
    clock.note(6)
    assert clock.total == 10  # absorbed 4, not 6
    assert clock.expired() is True
    clock.note(6)
    assert clock.total == 10  # nothing more, ever


def test_uncapped_clock_never_expires():
    clock = PauseClock()  # cap_s = 0 ⇒ uncapped
    clock.note(10_000)
    assert clock.total == 10_000
    assert clock.expired() is False
    assert clock.remaining() > 10_000
    assert not math.isnan(clock.remaining())


def test_paused_elapsed_subtracts_and_floors_at_zero():
    clock = PauseClock(cap_s=300)
    clock.note(12)
    assert clock.paused_elapsed(start=100, now=130) == 18
    big = PauseClock(cap_s=300)
    big.note(40)
    assert big.paused_elapsed(start=100, now=130) == 0  # never negative


def test_paused_elapsed_defaults_to_now(fake_clock):
    """No explicit `now` ⇒ one monotonic read; result ≥ 0 and monotone across calls."""
    clock = PauseClock(cap_s=300)
    start = time.monotonic()
    first = clock.paused_elapsed(start)
    assert first >= 0
    second = clock.paused_elapsed(start)
    assert second >= first


def test_describe_names_absorbed_and_cap():
    clock = PauseClock(cap_s=300)
    assert clock.describe() == ""  # nothing absorbed ⇒ nothing to say
    clock.note(12)
    text = clock.describe()
    assert text == "+12s captcha wait (cap 300s, 288s left)"
    uncapped = PauseClock()
    uncapped.note(7)
    assert "+7s captcha wait" in uncapped.describe()
    assert "(cap" not in uncapped.describe()  # no cap to report


def test_remaining_never_negative():
    clock = PauseClock(cap_s=5)
    clock.note(99)
    assert clock.remaining() == 0
    assert clock.total == 5
    assert clock.expired()


def test_clock_is_not_shared_between_waits():
    """One clock per generation wait: charging one never touches another."""
    first, second = PauseClock(cap_s=10), PauseClock(cap_s=10)
    first.note(10)
    assert first.expired() and not second.expired()
    assert second.total == 0 and second.remaining() == 10
