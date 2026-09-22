"""One connection per Firefox, reused — the "Incoming Connection" fix (I-64).

Firefox prompts the user to authorise **every incoming debugger connection**, so
the number of connections the app opens is the number of dialogs the user sees.
These tests count connections for that reason.
"""

import asyncio

import pytest

from app.browser.rdp.session_cache import SessionCache
from tests.rdp_fake_firefox import FakeFirefox

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.fixture
async def firefox():
    server = FakeFirefox()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def cache():
    c = SessionCache()
    yield c
    await c.close_all()


async def test_the_same_endpoint_is_attached_once(cache, firefox):
    first = await cache.acquire("127.0.0.1", firefox.port, 3)
    second = await cache.acquire("127.0.0.1", firefox.port, 3)
    assert first is second and firefox.connections == 1


async def test_concurrent_callers_share_one_connection(cache, firefox):
    """Two scans racing must not each open a link — that would be two dialogs."""
    sessions = await asyncio.gather(*[cache.acquire("127.0.0.1", firefox.port, 3)
                                      for _ in range(5)])
    assert len({id(s) for s in sessions}) == 1
    assert firefox.connections == 1


async def test_two_browsers_get_their_own_sessions(cache, firefox):
    other = FakeFirefox()
    await other.start()
    try:
        a = await cache.acquire("127.0.0.1", firefox.port, 3)
        b = await cache.acquire("127.0.0.1", other.port, 3)
        assert a is not b
        assert firefox.connections == 1 and other.connections == 1
    finally:
        await other.stop()


async def test_a_dead_session_is_replaced(cache, firefox):
    first = await cache.acquire("127.0.0.1", firefox.port, 3)
    await first.transport.close()
    second = await cache.acquire("127.0.0.1", firefox.port, 3)
    assert second is not first and second.is_attached
    assert firefox.connections == 2


async def test_release_detaches_and_forgets(cache, firefox):
    await cache.acquire("127.0.0.1", firefox.port, 3)
    await cache.release("127.0.0.1", firefox.port)
    assert cache.peek("127.0.0.1", firefox.port) is None
    await cache.acquire("127.0.0.1", firefox.port, 3)
    assert firefox.connections == 2


async def test_releasing_an_unknown_endpoint_is_harmless(cache):
    await cache.release("127.0.0.1", 9999)
    assert cache.peek("127.0.0.1", 9999) is None


async def test_close_all_detaches_every_browser(cache, firefox):
    other = FakeFirefox()
    await other.start()
    try:
        await cache.acquire("127.0.0.1", firefox.port, 3)
        await cache.acquire("127.0.0.1", other.port, 3)
        await cache.close_all()
        assert cache.peek("127.0.0.1", firefox.port) is None
        assert cache.peek("127.0.0.1", other.port) is None
    finally:
        await other.stop()


async def test_an_unreachable_browser_raises_and_caches_nothing(cache):
    """RULE 4: a refused port is broken — it must not leave a dead entry behind."""
    with pytest.raises(OSError):
        await cache.acquire("127.0.0.1", 1, 2)
    assert cache.peek("127.0.0.1", 1) is None


async def test_a_failing_detach_still_forgets_the_session(cache, firefox):
    session = await cache.acquire("127.0.0.1", firefox.port, 3)

    async def boom():
        raise OSError("socket already gone")

    session.detach = boom
    await cache.release("127.0.0.1", firefox.port)
    assert cache.peek("127.0.0.1", firefox.port) is None
