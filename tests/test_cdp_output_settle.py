"""S3 output helper units: one definition per helper; deterministic clock boundary."""
import asyncio

from unittest.mock import AsyncMock
from types import SimpleNamespace as NS

import pytest

from app.browser.cdp_arena import output
from app.core.pause_clock import PauseClock

pytestmark = pytest.mark.unit


@pytest.mark.target('app.browser.cdp_arena.output:_settle_timed')
@pytest.mark.parametrize('capped', [None, 300, 2])
@pytest.mark.parametrize('failure', [None, RuntimeError, asyncio.CancelledError])
async def test_settle_timed(monkeypatch, capped, failure):
    times = iter([100, 103])
    monkeypatch.setattr(output, 'time', NS(monotonic=lambda: next(times)))
    clock = None if capped is None else PauseClock(capped)
    settler = AsyncMock(side_effect=failure)
    if failure:
        with pytest.raises(failure):
            await output._settle_timed(settler, clock)
    else:
        await output._settle_timed(settler, clock)
    settler.assert_awaited_once()
    if clock is not None:
        assert clock.total == (0 if failure else min(capped, 3))


@pytest.mark.target('app.browser.cdp_arena.output:_timeout_text')
@pytest.mark.parametrize('result,expected', [({}, 'Timeout after 5000ms'),
    ({'pause_note': ''}, 'Timeout after 5000ms'),
    ({'pause_note': '+12s captcha wait (cap 300s, 288s left)', 'paused_s': 12},
     'Timeout after 5000ms (+12s captcha wait (cap 300s, 288s left))')])
def test_timeout_text(result, expected):
    assert output._timeout_text(result, 5000) == expected
