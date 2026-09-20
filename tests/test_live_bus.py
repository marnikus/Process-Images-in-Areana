"""S4 LiveBus units; each method has one owner and explicit state scenarios."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest

from app.services.live.bus import LiveBus, live_bus

pytestmark = pytest.mark.unit


@pytest.mark.target('app.services.live.bus:LiveBus.__init__')
def test_init():
    a, b = LiveBus(), LiveBus()
    assert a._reasons == [] and a._event is None and a._loop is None
    a._reasons.append('a')
    assert b._reasons == []


@pytest.mark.target('app.services.live.bus:LiveBus.attach')
def test_attach():
    bus = LiveBus()
    for loop in [object(), object()]:
        bus.attach(loop)
        assert bus._loop is loop


@pytest.mark.target('app.services.live.bus:LiveBus.wake')
@pytest.mark.parametrize('state', ['unattached', 'attached', 'closed'])
def test_wake(state):
    bus = LiveBus()
    callback = Mock(side_effect=RuntimeError('closed') if state == 'closed' else None)
    event = NS(set=Mock())
    if state != 'unattached':
        bus._loop, bus._event = NS(call_soon_threadsafe=callback), event
    bus.wake('queue')
    assert bus._reasons == ['queue']
    assert callback.call_count == (0 if state == 'unattached' else 1)
    if state != 'unattached':
        callback.assert_called_once_with(event.set)


@pytest.mark.target('app.services.live.bus:LiveBus.wait')
@pytest.mark.parametrize('mode', ['pending', 'wake', 'timeout', 'cancel', 'before_attach'])
async def test_wait(mode):
    bus = LiveBus()
    if mode == 'pending':
        bus.attach(asyncio.get_running_loop())
    if mode in ('pending', 'before_attach'):
        bus.wake('reset_all')
        bus.wake('scan')
    bus.attach(asyncio.get_running_loop())
    if mode in ('pending', 'before_attach'):
        assert await bus.wait(0.05) == 'reset_all+scan'
        assert await bus.wait(0.001) == ''
    else:
        task = asyncio.create_task(bus.wait(0.02))
        await asyncio.sleep(0)
        if mode == 'wake':
            bus.wake('queue')
        if mode == 'cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task == ('queue' if mode == 'wake' else '')
        assert bus._event is None


@pytest.mark.target('app.services.live.bus:LiveBus.throttle')
@pytest.mark.parametrize('key,elapsed,expected', [('same', 0, False), ('same', .4, True), ('different', 0, True)])
def test_throttle(key, elapsed, expected):
    bus = LiveBus()
    now = [0.0]
    bus._clock = lambda: now[0]
    assert bus.throttle('same', 300) is True
    now[0] = elapsed
    assert bus.throttle(key, 300) is expected


@pytest.mark.target('app.services.live.bus:LiveBus.reasons')
def test_reasons():
    bus = LiveBus()
    bus._reasons = ['queue']
    copy = bus.reasons()
    copy.append('external')
    assert bus.reasons() == ['queue']


@pytest.mark.target('app.services.live.bus:live_bus')
@pytest.mark.parametrize('frozen', [False, True])
def test_live_bus(frozen):
    host = object() if frozen else NS()
    bus = live_bus(host)
    assert isinstance(bus, LiveBus)
    if not frozen:
        assert live_bus(host) is bus
