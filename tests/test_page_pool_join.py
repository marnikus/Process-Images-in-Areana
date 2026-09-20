"""S1 / L-1 regression: the pool join slot schedules on the REAL service seam.

`PagePoolMixin.connect_page_pool` is the slot behind "Add Selected Tab to
Pool" (JS `poolConnectBtn`) and the join path a later URL reconciler reuses.
Before S1 it called `self._schedule_coro(...)`, an attribute that no
production object has, so the slot always answered `{"ok": false}` — and
the panel tests hid it by injecting that attribute on their fake host (L-6).

RULE 8: the host here deliberately has NO `_schedule_coro`; the only
scheduling seam is the module-level `schedule_coro` imported into
`app.ui.panels.page_pool` from `app.services.run_state`.
Plan: docs/archive/2026-09-20-dynamic-urls-and-worker-debug/tdd-interfaces.md §S1
"""

import json
from pathlib import Path

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.ui.panels import page_pool
from app.ui.panels.page_pool import PagePoolMixin, do_connect_page_pool

pytestmark = pytest.mark.unit

WS_URL = "ws://127.0.0.1:9222/devtools/page/t1"


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class Host(PagePoolMixin):
    """Real mixin on a bare host: no `_schedule_coro`, that omission is the point."""

    def __init__(self, pool):
        self._page_pool = pool
        self.logs = []
        self._log = lambda msg, level="info": self.logs.append((level, msg))
        self.page_pool_updated = Emitter()
        self._emit_pool_status = lambda: None
        self._persist_cooldowns = lambda: None


def test_connect_page_pool_schedules_on_the_real_helper(monkeypatch):
    calls = []

    def spy(bridge, coro):
        calls.append((bridge, coro))

    monkeypatch.setattr(page_pool, "schedule_coro", spy)
    host = Host(PagePool())

    reply = json.loads(host.connect_page_pool(WS_URL))

    assert reply == {"ok": True}
    assert len(calls) == 1
    bridge, coro = calls[0]
    assert bridge is host
    assert coro.cr_code.co_name == "do_connect_page_pool"
    coro.close()
    assert any("Adding tab to pool" in msg for _, msg in host.logs)


def test_no_private_scheduler_survives_in_the_pool_panel():
    text = Path(page_pool.__file__).read_text(encoding="utf-8")
    assert "_schedule_coro" not in text, "L-6: a private scheduler attribute exists nowhere in production"
    assert "schedule_coro(self," in text


def test_connect_page_pool_error_branches_unchanged(monkeypatch):
    """Equivalence (green at base): the reply vocabulary the JS parses stays."""
    monkeypatch.setattr(page_pool, "schedule_coro", lambda bridge, coro: coro.close())
    host = Host(PagePool())
    assert json.loads(host.connect_page_pool("")) == {"ok": False, "error": "empty ws_url"}
    host._page_pool = None
    assert json.loads(host.connect_page_pool(WS_URL)) == {"ok": False, "error": "pool not initialized"}


async def test_scheduled_coroutine_joins_the_pool(monkeypatch):
    """Equivalence (green at base): the coroutine S1 schedules is the one that joins."""
    class FakeClient:
        pass

    async def fake_connect(bridge, ws_url):
        return FakeClient()

    async def fake_info(bridge, tab_id, ws_url):
        return "T", "https://arena.ai"

    monkeypatch.setattr(page_pool, "connect_pool_client", fake_connect)
    monkeypatch.setattr(page_pool, "resolve_tab_info", fake_info)
    monkeypatch.setattr(page_pool, "restore_page_state", lambda bridge, tab_id: None)
    monkeypatch.setattr("app.browser.cdp_arena.CDPArenaController", lambda client, log_callback: object())
    host = Host(PagePool())
    emitted = []
    host._emit_pool_status = lambda: emitted.append(True)

    await do_connect_page_pool(host, "ws://x/devtools/page/t9")

    page = host._page_pool.get_page("t9")
    assert page is not None and page.title == "T" and page.url == "https://arena.ai"
    assert isinstance(page, PageInfo)
    assert emitted == [True]
    assert any("Pool added t9" in msg for _, msg in host.logs)
