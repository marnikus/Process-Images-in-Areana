"""S1 — the pool join reaches the real scheduler (L-1) and stays there (L-6).

The host below is deliberately built WITHOUT `_schedule_coro`: that omission is
the test. A double that supplies the missing attribute is what hid this defect
for months (tdd-interfaces.md §0.3 L-6), so it may never come back.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.ui.panels import page_pool


class Emitter:
    def __init__(self):
        self.count = 0

    def emit(self, *_a):
        self.count += 1


def make_host(**over):
    """A bridge-shaped host with the production attribute surface only."""
    emitted = []
    host = SimpleNamespace(
        _page_pool=over.pop("pool", PagePool()),
        page_pool_updated=Emitter(),
        _log=lambda *_a, **_k: None,
        _emit_pool_status=lambda: emitted.append(1),
    )
    host.pool_emits = emitted
    for key, value in over.items():
        setattr(host, key, value)
    host.connect_page_pool = page_pool.PagePoolMixin.connect_page_pool.__get__(host)
    return host


@pytest.mark.unit
def test_connect_page_pool_schedules_on_the_real_helper(monkeypatch):
    calls = []
    monkeypatch.setattr(page_pool, "schedule_coro", lambda bridge, coro: calls.append((bridge, coro)))
    host = make_host()

    reply = json.loads(host.connect_page_pool("ws://127.0.0.1:9222/devtools/page/t1"))

    assert reply["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] is host
    assert calls[0][1].cr_code.co_name == "do_connect_page_pool"
    calls[0][1].close()


@pytest.mark.unit
def test_no_private_scheduler_survives_in_the_pool_panel():
    text = Path("app/ui/panels/page_pool.py").read_text(encoding="utf-8")
    assert "_schedule_coro" not in text
    assert "schedule_coro(self," in text


@pytest.mark.unit
def test_connect_page_pool_error_branches_unchanged(monkeypatch):
    """Equivalence (green at base): the reply vocabulary the JS parses."""
    monkeypatch.setattr(page_pool, "schedule_coro", lambda *_a: None)
    assert json.loads(make_host().connect_page_pool(""))["error"] == "empty ws_url"
    assert json.loads(make_host(pool=None).connect_page_pool("ws://x"))["error"] == "pool not initialized"


@pytest.mark.unit
def test_scheduled_coroutine_joins_the_pool(event_loop, monkeypatch):
    """Equivalence (green at base): the coroutine S1 schedules is the one that works."""
    class FakeClient:
        pass

    async def fake_connect(_bridge, _ws):
        return FakeClient()

    async def fake_info(_bridge, _tab, _ws):
        return "T", "https://arena.ai/c/x"

    monkeypatch.setattr(page_pool, "connect_pool_client", fake_connect)
    monkeypatch.setattr(page_pool, "resolve_tab_info", fake_info)
    monkeypatch.setattr(page_pool, "restore_page_state", lambda *_a: None)
    host = make_host()

    event_loop.run_until_complete(
        page_pool.do_connect_page_pool(host, "ws://127.0.0.1:9222/devtools/page/t9"))

    page = host._page_pool.get_page("t9")
    assert page is not None and page.title == "T"
    assert host.pool_emits == [1]  # emitted through the _emit_pool_status seam
