"""S1 · L-1 — the pool join reaches the real scheduler.

`connect_page_pool` (the slot behind "Add Selected Tab to Pool", and the path
the S6 reconciler uses to join tabs) used to call `self._schedule_coro(...)`,
an attribute no production object has; the slot's `except Exception` turned
the AttributeError into an error JSON, and the test doubles that defined
`_schedule_coro` hid it (L-6). RULE 8: real PagePool, the seam under test
(`schedule_coro`) is spied at module level, never replaced on the host.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.services import run_state
from app.ui.panels import page_pool
from app.ui.panels.page_pool import PagePoolMixin, do_connect_page_pool

pytestmark = pytest.mark.unit


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


def make_host(pool=PagePool):
    """A PagePoolMixin host WITHOUT any private `_schedule_coro` attribute."""
    class Host(PagePoolMixin):
        pass

    host = Host()
    host._page_pool = pool() if callable(pool) else pool
    host.logs = []
    host._log = lambda msg, level="info": host.logs.append((level, msg))
    host._emit_pool_status = lambda: None
    host.page_pool_updated = Emitter()
    return host


class SchedulerSpy:
    def __init__(self):
        self.calls = []

    def __call__(self, bridge, coro):
        self.calls.append((bridge, coro))
        return None


def test_connect_page_pool_schedules_on_the_real_helper(monkeypatch):
    spy = SchedulerSpy()
    monkeypatch.setattr(page_pool, "schedule_coro", spy)
    host = make_host()

    reply = json.loads(host.connect_page_pool("ws://127.0.0.1:9222/devtools/page/t1"))

    assert reply == {"ok": True}
    assert len(spy.calls) == 1
    bridge, coro = spy.calls[0]
    assert bridge is host
    assert coro.cr_code.co_name == "do_connect_page_pool"
    coro.close()


def test_no_private_scheduler_survives_in_the_pool_panel():
    text = Path(page_pool.__file__).read_text(encoding="utf-8")
    assert "_schedule_coro" not in text, "L-1 is back: a private scheduler attribute"
    assert "schedule_coro(self," in text


def test_connect_page_pool_error_branches_unchanged():
    host = make_host()
    assert json.loads(host.connect_page_pool("")) == {"ok": False, "error": "empty ws_url"}
    host._page_pool = None
    assert json.loads(host.connect_page_pool("ws://x/devtools/page/t")) == \
        {"ok": False, "error": "pool not initialized"}


async def test_scheduled_coroutine_joins_the_pool(monkeypatch):
    host = make_host()
    client = SimpleNamespace(connected=True)

    async def fake_connect(bridge, ws_url):
        return client

    async def fake_resolve(bridge, tab_id, ws_url):
        return "T", "https://arena.ai"

    monkeypatch.setattr(page_pool, "connect_pool_client", fake_connect)
    monkeypatch.setattr(page_pool, "resolve_tab_info", fake_resolve)
    monkeypatch.setattr(page_pool, "restore_page_state", lambda bridge, tab_id: None)
    monkeypatch.setattr(run_state, "restore_page_state", lambda bridge, tab_id: None)

    await do_connect_page_pool(host, "ws://x/devtools/page/t9")

    page = host._page_pool.get_page("t9")
    assert page is not None and page.title == "T"
    assert any("Pool added t9" in msg for _, msg in host.logs)
