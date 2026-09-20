"""S3 — D-26 extractions in cdp_arena/output.py: the settle is timed, the
timeout text carries the pause evidence. `_security_gate`'s span/CC/nest are
unchanged (it only swapped `await settler()` for the timed wrapper)."""

import asyncio

import pytest

from app.browser.cdp_arena.output import _settle_timed, _timeout_text

pytestmark = pytest.mark.unit


async def test_settle_timed_charges_only_the_settles_own_duration():
    from app.core.pause_clock import PauseClock
    clock = PauseClock(cap_s=300)
    called = []

    async def settler():
        await asyncio.sleep(0.05)
        called.append("settled")

    await _settle_timed(settler, clock)
    assert called == ["settled"]
    assert 0.03 <= clock.total <= 0.5  # the settle's wall time, nothing more


async def test_settle_timed_without_a_clock_still_settles():
    called = []

    async def settler():
        called.append("settled")

    await _settle_timed(settler, None)  # Watcher-OFF: no clock installed (D-23)
    assert called == ["settled"]


async def test_timeout_text_is_unchanged_without_a_pause():
    assert _timeout_text({}, 5000) == "Timeout after 5000ms"
    assert _timeout_text({"pause_note": ""}, 5000) == "Timeout after 5000ms"


def test_timeout_text_carries_the_pause_evidence():
    result = {"pause_note": "+12s captcha wait (cap 300s, 288s left)", "paused_s": 12.0}
    text = _timeout_text(result, 5000)
    assert text.startswith("Timeout after 5000ms (")
    assert "+12s captcha wait" in text and text.endswith(")")
