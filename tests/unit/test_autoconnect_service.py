"""Unit tests — AutoConnectService loop: start scan, event wake, stop (RULE 7), status.

The service is tested with a fake tab fetcher and the real PageLinker + PagePool,
so the wiring that runs in production is the wiring under test (RULE 8).
"""

from __future__ import annotations

import asyncio

import pytest

from app.browser.autoconnect_config import AutoConnectConfig
from app.browser.autoconnect_linker import PageLinker
from app.browser.autoconnect_service import AutoConnectService, ScanScheduler, ServiceHooks
from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo

def pool_ids(pool) -> list:
    """Sorted page ids in the pool — the pool is the source of truth."""
    return sorted(p["tab_id"] for p in pool.status_snapshot()["pages"])


def tab(pid: str, url: str = "https://arena.ai/c/1", title: str = "Arena") -> dict:
    return {"id": pid, "title": title, "url": url, "ws_url": f"ws://127.0.0.1:9223/devtools/page/{pid}"}


class FakeChrome:
    """Stand-in for CDPClient.fetch_tabs — records the endpoint it was asked for."""

    def __init__(self, tabs=None, error: str = ""):
        self.tabs = list(tabs or [])
        self.error = error
        self.calls: list = []

    async def fetch_tabs(self, host=None, port=None, strict_host=True):
        self.calls.append({"host": host, "port": port, "strict_host": strict_host})
        if self.error:
            raise ConnectionError(self.error)
        return list(self.tabs)


def make_service(chrome=None, tabs=None, config=None, pool=None, watcher=False, error=""):
    chrome = chrome or FakeChrome(tabs=tabs, error=error)
    pool = pool if pool is not None else PagePool()
    statuses: list = []
    logs: list = []

    async def connect_page(pg: dict) -> bool:
        pool.add_page(PageInfo(tab_id=pg["page_id"], ws_url=pg["ws_url"], title=pg["title"], url=pg["url"]))
        return True

    linker = PageLinker(pool=pool, connect_page=connect_page,
                        disconnect_page=pool.remove_page,
                        logger=lambda m, lvl="info": logs.append((m, lvl)))
    cfg = config or AutoConnectConfig(enabled=True, url_pattern="arena.ai", interval_ms=1000,
                                      host="127.0.0.1", port=9223)
    svc = AutoConnectService(fetch_tabs=chrome.fetch_tabs, linker=linker, config=cfg,
                             hooks=ServiceHooks(on_status=statuses.append,
                                                logger=lambda m, lvl="info": logs.append((m, lvl))))
    # no browser-level CDP endpoint in unit tests — the timer path is what we exercise
    loop = ScanScheduler(svc, watcher_factory=lambda: None if not watcher else None)
    svc.loop = loop  # convenience handle for tests
    return svc, chrome, pool, statuses, logs


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scan_once_links_every_matching_page():
    svc, chrome, pool, statuses, logs = make_service(tabs=[tab("AAA"), tab("BBB"), tab("CCC", url="https://x.dev/")])
    report = await svc.scan_once()
    assert report["matched"] == 2
    assert sorted(pool_ids(pool)) == ["AAA", "BBB"]
    assert report["endpoint"] == "127.0.0.1:9223"
    assert statuses[-1]["connected_now"] == 2
    assert any("2 matched" in m for m, _l in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scan_reports_broken_endpoint_as_error_not_empty():
    svc, _chrome, pool, statuses, logs = make_service(error="Port 9223 not open on 127.0.0.1")
    report = await svc.scan_once()
    assert report["ok"] is False
    assert "not open" in report["error"]
    assert report["matched"] == 0
    assert pool_ids(pool) == []
    assert statuses[-1]["ok"] is False
    assert any(lvl == "warn" and "scan failed" in m for m, lvl in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_zero_matching_pages_is_reported_as_empty():
    svc, _chrome, _pool, _statuses, logs = make_service(tabs=[tab("CCC", url="https://docs.python.org/")])
    report = await svc.scan_once()
    assert report["ok"] is True
    assert report["matched"] == 0
    assert any(lvl == "warn" and "nothing to connect" in m for m, lvl in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_scans_immediately_and_rescans_on_interval():
    svc, chrome, pool, _statuses, _logs = make_service(tabs=[tab("AAA")])
    svc.config.interval_ms = 1000
    task = asyncio.ensure_future(svc.loop.run())
    await asyncio.sleep(0.05)
    assert chrome.calls, "must scan on start without a manual Add"
    assert pool_ids(pool) == ["AAA"]
    # new tab appears — next periodic scan links it
    chrome.tabs.append(tab("BBB"))
    await asyncio.sleep(1.2)
    assert sorted(pool_ids(pool)) == ["AAA", "BBB"]
    await svc.loop.stop()
    assert task.done()
    assert svc.loop.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_tab_event_triggers_immediate_rescan():
    svc, chrome, pool, _statuses, _logs = make_service(tabs=[tab("AAA")])
    svc.config.interval_ms = 60_000  # long poll — only an event can wake it
    task = asyncio.ensure_future(svc.loop.run())
    await asyncio.sleep(0.05)
    assert pool_ids(pool) == ["AAA"]
    chrome.tabs.append(tab("BBB"))
    before = len(chrome.calls)
    svc.loop.request_scan("Target.targetCreated")
    await asyncio.sleep(0.05)
    assert len(chrome.calls) > before
    assert sorted(pool_ids(pool)) == ["AAA", "BBB"]
    await svc.loop.stop()
    assert task.done()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_request_scan_is_thread_safe_from_watcher_thread():
    svc, chrome, _pool, _statuses, _logs = make_service(tabs=[tab("AAA")])
    svc.config.interval_ms = 60_000
    task = asyncio.ensure_future(svc.loop.run())
    await asyncio.sleep(0.05)
    calls = len(chrome.calls)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: svc.loop.request_scan("thread"))
    await asyncio.sleep(0.05)
    assert len(chrome.calls) > calls
    await svc.loop.stop()
    assert task.done()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_closed_page_is_dropped_on_rescan():
    svc, chrome, pool, statuses, logs = make_service(tabs=[tab("AAA"), tab("BBB")])
    await svc.scan_once()
    assert sorted(pool_ids(pool)) == ["AAA", "BBB"]
    chrome.tabs = [tab("AAA")]
    report = await svc.scan_once()
    assert report["removed"] == ["BBB"]
    assert pool_ids(pool) == ["AAA"]
    assert any(lvl == "warn" and "removed from pool" in m for m, lvl in logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_is_prompt_even_with_long_interval():
    svc, _chrome, _pool, _statuses, _logs = make_service(tabs=[tab("AAA")])
    svc.config.interval_ms = 600_000
    task = asyncio.ensure_future(svc.loop.run())
    await asyncio.sleep(0.05)
    assert svc.loop.running is True
    started = asyncio.get_event_loop().time()
    await svc.loop.stop()
    assert asyncio.get_event_loop().time() - started < 1.0
    assert task.done()
    assert svc.loop.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_second_run_call_does_not_start_two_loops():
    svc, chrome, _pool, _statuses, _logs = make_service(tabs=[tab("AAA")])
    first = asyncio.ensure_future(svc.loop.run())
    await asyncio.sleep(0.02)
    await svc.loop.run()  # returns immediately, loop already running
    assert chrome.calls and len(chrome.calls) == 1
    await svc.loop.stop()
    assert first.done()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_status_callback_failure_never_kills_the_scan():
    svc, _chrome, pool, _statuses, _logs = make_service(tabs=[tab("AAA")])

    def boom(_report):
        raise RuntimeError("UI callback exploded")

    svc.hooks.on_status = boom
    report = await svc.scan_once()
    assert report["connected_now"] == 1
    assert pool_ids(pool) == ["AAA"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reload_config_switches_endpoint_and_pattern():
    svc, chrome, pool, _statuses, _logs = make_service(tabs=[tab("AAA", url="https://virt-chat.com/feed")])
    store = {"autoconnect_url_pattern": "arena.ai", "autoconnect_interval_ms": 2000,
             "autoconnect_enabled": True, "autoconnect_max_pages": 0,
             "autoconnect_primary": False, "cdp_host": "127.0.0.1", "cdp_port": 9222}
    cfg = svc.reload_config(lambda key, default=None: store.get(key, default))
    assert cfg.endpoint == "127.0.0.1:9222"
    assert await svc.scan_once() and pool_ids(pool) == []
    # user edits the stored pattern + port — next scan follows immediately
    store.update({"autoconnect_url_pattern": "virt-chat.com", "cdp_port": 9223})
    cfg = svc.reload_config(lambda key, default=None: store.get(key, default))
    assert cfg.endpoint == "127.0.0.1:9223"
    report = await svc.scan_once()
    assert report["matched"] == 1
    assert report["endpoint"] == "127.0.0.1:9223"
    assert pool_ids(pool) == ["AAA"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_halt_without_a_running_loop_is_safe():
    svc, _chrome, _pool, statuses, _logs = make_service(tabs=[tab("AAA")])
    assert svc.loop.halt() is None
    await svc.loop.stop()  # stop with nothing running still publishes the final state
    assert statuses[-1]["running"] is False
    assert statuses[-1]["reason"] == "stopped"
    assert svc.loop.running is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_broken_watcher_factory_never_blocks_the_timer():
    svc, chrome, pool, _statuses, _logs = make_service(tabs=[tab("AAA")])

    def broken_factory():
        raise RuntimeError("websockets exploded")

    scheduler = ScanScheduler(svc, watcher_factory=broken_factory)
    task = asyncio.ensure_future(scheduler.run())
    await asyncio.sleep(0.05)
    assert pool_ids(pool) == ["AAA"]  # the poll path still linked the page
    assert scheduler._watcher is None
    await scheduler.stop()
    assert task.done()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_scan_crash_is_logged_and_the_loop_survives():
    svc, chrome, pool, _statuses, logs = make_service(tabs=[tab("AAA")])

    async def explode():
        raise RuntimeError("boom")

    svc.linker.reconcile = explode
    scheduler = ScanScheduler(svc, watcher_factory=lambda: None)
    svc.config.interval_ms = 1000
    task = asyncio.ensure_future(scheduler.run())
    await asyncio.sleep(0.05)
    assert any(lvl == "error" and "crashed" in m for m, lvl in logs)
    assert scheduler.running is True
    await scheduler.stop()
    assert task.done()


@pytest.mark.unit
def test_service_hooks_swallow_logger_errors():
    def boom(_msg, _lvl="info"):
        raise RuntimeError("log handler exploded")

    hooks = ServiceHooks(logger=boom)
    hooks.log("anything", "info")  # must not raise


@pytest.mark.unit
def test_publish_without_a_sink_is_a_noop():
    hooks = ServiceHooks()
    hooks.publish({"matched": 0})  # no on_status → nothing to do
