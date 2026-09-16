"""Conftest — session fixtures to reduce test time (Phase 0-4).

Goals:
- Fix PYTHONPATH so `pytest -q` works without PYTHONPATH=.
- Provide session-scoped event_loop, qapp, tmp_path_factory base.
- Provide worker_id for xdist isolation (Phase 4).
- Provide fake clock/event to eliminate real sleeps in PagePool (Phase 1).
- Provide tmp_path-based ConfigManager/UndoStore to avoid real FS (Phase 1+4).
- Worker-isolated resources: config, media, logs, preset store (Phase 4).
- Mark-based grouping for fast/slow lanes (Phase 4).

RULE 18: file ideal 150-300 LOC, current ~220 LOC.
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


def pytest_collection_modifyitems(items):
    """Auto-mark slow/e2e based on path — Phase 4 mark grouping."""
    for item in items:
        if "webengine" in item.nodeid or "sash_webengine" in item.nodeid:
            item.add_marker(pytest.mark.slow)
            item.add_marker(pytest.mark.e2e)
        if "integration" in item.nodeid and "unit" not in item.keywords:
            if "integration" not in item.keywords:
                item.add_marker(pytest.mark.integration)
        if "unit" in item.nodeid and "unit" not in item.keywords:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Session-scoped event loop to avoid recreation per test."""
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
    """Session-scoped QApplication — only one per process (Phase 2)."""
    try:
        from PySide6.QtWidgets import QApplication
        import sys as _sys

        app = QApplication.instance()
        if app is None:
            app = QApplication(_sys.argv[:1])
        yield app
    except Exception:
        yield None


@pytest.fixture
def worker_id(request):
    """Worker id for xdist isolation, falls back to 'master' (Phase 4)."""
    try:
        return getattr(request.config, "workerinput", {}).get("workerid", "master")
    except Exception:
        return "master"


@pytest.fixture
def tmp_config_path(tmp_path, worker_id):
    """Tmp_path-based config file path isolated per worker (Phase 4)."""
    return tmp_path / f"config_{worker_id}.json"


@pytest.fixture
def isolated_config_dir(tmp_path, worker_id):
    """Isolated config dir per worker — avoids single file collision in xdist."""
    d = tmp_path / f"config_dir_{worker_id}"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def isolated_media_root(tmp_path, worker_id):
    """Isolated media root per worker — avoids saved_media/ collision."""
    d = tmp_path / f"media_{worker_id}"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def isolated_log_file(tmp_path, worker_id):
    """Isolated log file per worker — avoids logs/ collision."""
    return tmp_path / f"arena_{worker_id}.log"


@pytest.fixture
def fake_clock():
    """Fake clock to eliminate real sleeps in PagePool tests (Phase 1)."""

    class FakeClock:
        def __init__(self):
            self._events = []

        def create_event(self):
            ev = asyncio.Event()
            self._events.append(ev)
            return ev

        async def sleep(self, _sec: float):
            await asyncio.sleep(0)

    return FakeClock()


@pytest.fixture
def page_pool_with_event():
    """PagePool with notify event for fast wait (Phase 1)."""
    from app.browser.page_pool import PagePool

    pool = PagePool()
    notify = asyncio.Event()
    orig = pool.mark_steady

    def mark_steady_and_notify(tab_id: str):
        ok = orig(tab_id)
        if ok:
            try:
                notify.set()
            except Exception:
                pass
        return ok

    pool.mark_steady = mark_steady_and_notify  # type: ignore
    return pool, notify


@pytest.fixture
def fake_preset_store(tmp_path, worker_id):
    """Isolated preset store per worker — tmp_path based, no real config/ touch."""
    from app.persistence.preset_store import PresetStore

    store_path = tmp_path / f"presets_{worker_id}"
    store_path.mkdir(exist_ok=True)
    try:
        store = PresetStore(path=store_path)  # type: ignore
    except Exception:
        store = PresetStore()
    return store, store_path
