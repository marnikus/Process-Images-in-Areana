"""Conftest — session fixtures to reduce test time (Phase 0+1).

Goals:
- Fix PYTHONPATH so `pytest -q` works without PYTHONPATH=.
- Provide session-scoped event_loop, qapp, tmp_path_factory base.
- Provide worker_id for xdist isolation.
- Provide fake clock/event to eliminate real sleeps in PagePool.
- Provide tmp_path-based ConfigManager/UndoStore to avoid real FS.

RULE 18: file ideal 150-300 LOC, current 120 LOC.
RULE 16: no function >30 LOC, CC ≤10, nesting ≤4.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Generator

import pytest

# Fix sys.path — project root is parent of tests/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Session-scoped event loop to avoid recreation per test.

    Prevents loop mismatch that previously froze mouse clicks (PagePool used asyncio.Lock
    bound to different loop). Now PagePool uses threading.RLock, but session loop still
    reduces time.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    try:
        loop.run_until_complete(loop.shutdown_asyncgens())
    finally:
        loop.close()
        asyncio.set_event_loop(None)


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication if PySide6 available, else None.

    Only one QApp per process — session scope avoids expensive recreation.
    """
    try:
        from PySide6.QtWidgets import QApplication
        import sys as _sys

        app = QApplication.instance()
        if app is None:
            app = QApplication(_sys.argv[:1])
        yield app
        # Don't quit — session ends
    except Exception:
        yield None


@pytest.fixture
def worker_id(request):
    """Worker id for xdist isolation, falls back to 'master'."""
    try:
        return getattr(request.config, "workerinput", {}).get("workerid", "master")
    except Exception:
        return "master"


@pytest.fixture
def tmp_config_path(tmp_path, worker_id):
    """Tmp_path-based config file path isolated per worker."""
    return tmp_path / f"config_{worker_id}.json"


@pytest.fixture
def fake_clock():
    """Fake clock to eliminate real sleeps in PagePool tests.

    Provides Event that can be set immediately instead of sleep.
    """

    class FakeClock:
        def __init__(self):
            self._events = []

        def create_event(self):
            ev = asyncio.Event()
            self._events.append(ev)
            return ev

        async def sleep(self, _sec: float):
            # No real sleep — yield control once
            await asyncio.sleep(0)

    return FakeClock()


@pytest.fixture
def page_pool_with_event():
    """PagePool with helper to create notify event for fast wait.

    Returns (pool, notify_event) where notify_event is set when page becomes steady.
    """
    from app.browser.page_pool import PagePool

    pool = PagePool()
    notify = asyncio.Event()

    original_mark_steady = pool.mark_steady

    def mark_steady_and_notify(tab_id: str):
        ok = original_mark_steady(tab_id)
        if ok:
            try:
                notify.set()
            except Exception:
                pass
        return ok

    pool.mark_steady = mark_steady_and_notify  # type: ignore
    return pool, notify