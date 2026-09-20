"""S1L-1: real pool slot → scheduler → join; only the CDP transport is fake."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageStatus
from app.services.run_state import schedule_coro
from app.ui.panels import page_pool as panel
from tests.test_panel_slots import make_host

pytestmark = pytest.mark.unit
WS_URL = "ws://127.0.0.1:9222/devtools/page/t9"


@pytest.fixture
async def join_host(tmp_path, cdp_server):
    pool = PagePool()
    host, _ = make_host(
        (panel.PagePoolMixin,), _page_pool=pool,
        _bg_loop=asyncio.get_running_loop(), config=SimpleNamespace(dir=tmp_path),
        cdp=SimpleNamespace(_current_title="Arena", _current_url="https://arena.ai/c"),
        _emit_pool_status=Mock(),
    )
    yield host
    for client in pool._clients.values():
        await client.disconnect()


async def test_connect_page_pool_schedules_on_the_real_helper(join_host, monkeypatch):
    scheduled = []

    def spy(bridge, coro):
        future = schedule_coro(bridge, coro)
        scheduled.append((bridge, coro, future))
        return future

    monkeypatch.setattr(panel, "schedule_coro", spy, raising=False)
    assert not hasattr(join_host, "_schedule_coro")
    assert json.loads(join_host.connect_page_pool(WS_URL)) == {"ok": True}
    assert len(scheduled) == 1
    bridge, coro, future = scheduled[0]
    assert bridge is join_host and coro.cr_code.co_name == "do_connect_page_pool"
    await asyncio.wait_for(asyncio.wrap_future(future), timeout=2)
    assert join_host._page_pool.get_page("t9").status == PageStatus.STEADY
    join_host._emit_pool_status.assert_called_once_with()


def test_no_private_scheduler_survives_in_the_pool_panel():
    source = Path(panel.__file__).read_text(encoding="utf-8")
    assert "_schedule_coro" not in source
    assert "schedule_coro(self," in source


async def test_connect_page_pool_error_branches_unchanged(join_host, monkeypatch):
    scheduler = Mock(side_effect=AssertionError("invalid join must not schedule"))
    monkeypatch.setattr(panel, "schedule_coro", scheduler, raising=False)
    assert json.loads(join_host.connect_page_pool("")) == {"ok": False, "error": "empty ws_url"}
    join_host._page_pool = None
    assert json.loads(join_host.connect_page_pool(WS_URL)) == {
        "ok": False, "error": "pool not initialized",
    }
    scheduler.assert_not_called()


async def test_scheduled_coroutine_joins_the_pool(join_host, cdp_server):
    await panel.do_connect_page_pool(join_host, WS_URL)
    page = join_host._page_pool.get_page("t9")
    assert (page.title, page.url, page.ws_url) == ("Arena", "https://arena.ai/c", WS_URL)
    assert page.status == PageStatus.STEADY
    client, controller = join_host._page_pool.get_clients("t9")
    assert client.is_connected and controller is not None
    assert cdp_server.connects == [WS_URL]
    join_host._emit_pool_status.assert_called_once_with()
