"""Integration — auto-connect against a real HTTP CDP endpoint (no Chrome needed).

Runs the whole production chain: real ``CDPClient.fetch_tabs`` over HTTP against a
local ``/json/list`` server, real pattern detection, real ``PageLinker`` +
``PagePool``, real ``ScanScheduler`` timer. Only the Bridge is a stub, so this
proves the app links pages that a real debug port advertises (RULE 8).
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.browser.autoconnect_config import AutoConnectConfig
from app.browser.autoconnect_linker import PageLinker
from app.browser.autoconnect_service import AutoConnectService, ScanScheduler, ServiceHooks
from app.browser.cdp_client import CDPClient
from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.ui.autoconnect_pages import PageConnector

ARENA = "https://arena.ai/c/"


class FakeChrome:
    """Minimal Chrome remote-debugging endpoint: /json/list + /json/version."""

    def __init__(self):
        self.pages: list = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, payload):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.startswith("/json/list"):
                    self._send(list(outer.pages))
                elif self.path.startswith("/json/version"):
                    self._send({"Browser": "FakeChrome/1.0", "webSocketDebuggerUrl": ""})
                else:
                    self.send_error(404)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def set_pages(self, *ids_and_urls):
        self.pages = [
            {
                "id": pid,
                "type": "page",
                "title": f"Page {pid}",
                "url": url,
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/{pid}",
            }
            for pid, url in ids_and_urls
        ]


class FakeSignal:
    def __init__(self):
        self.emitted: list = []

    def emit(self, *args):
        self.emitted.append(args)


class LinkBridge:
    """Stub Bridge: registers pages in the real pool instead of opening websockets."""

    def __init__(self, pool: PagePool, cdp: CDPClient):
        self._page_pool = pool
        self.cdp = cdp
        self.logs: list = []
        self.pool_links: list = []
        self.primary_links: list = []
        self.status_emissions = 0
        self.pool_status_changed = FakeSignal()

    def _log(self, msg, level="info"):
        self.logs.append((msg, level))

    def _emit_pool_status_signal(self):
        self.pool_status_changed.emit()

    def _emit_pool_status(self):
        self.status_emissions += 1

    def _restore_cooldown(self, _tab_id):
        return None

    async def _do_connect_tab(self, ws_url):
        self.primary_links.append(ws_url)
        self._register(ws_url)

    async def _do_connect_page_pool(self, ws_url):
        self.pool_links.append(ws_url)
        self._register(ws_url)

    def _register(self, ws_url):
        """Same as Bridge._do_connect_*: pool membership changes are announced."""
        pid = ws_url.rsplit("/", 1)[-1]
        self._page_pool.add_page(PageInfo(tab_id=pid, ws_url=ws_url, title=f"Page {pid}", url=ARENA + pid))
        self._emit_pool_status()


def pool_ids(pool: PagePool) -> list:
    return sorted(p["tab_id"] for p in pool.status_snapshot()["pages"])


def build_stack(chrome: FakeChrome, pool: PagePool, config: AutoConnectConfig):
    cdp = CDPClient(host="127.0.0.1", port=chrome.port)
    bridge = LinkBridge(pool, cdp)
    connector = PageConnector(bridge, lambda: config)
    hooks = ServiceHooks(logger=lambda m, lvl="info": bridge.logs.append((m, lvl)))
    linker = PageLinker(pool=pool, connect_page=connector.link, disconnect_page=connector.unlink,
                        logger=hooks.log)
    service = AutoConnectService(fetch_tabs=connector.fetch, linker=linker, config=config, hooks=hooks)
    return bridge, service


@pytest.fixture
def chrome():
    server = FakeChrome().start()
    yield server
    server.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_endpoint_links_matching_pages_only(chrome):
    chrome.set_pages(
        ("AAA", ARENA + "one"),
        ("BBB", ARENA + "one"),  # same URL, different page id → its own page
        ("CCC", "https://docs.python.org/3/"),
        ("DDD", "devtools://devtools/bundled/inspector.html"),
    )
    pool = PagePool()
    config = AutoConnectConfig(url_pattern="arena.ai", host="127.0.0.1", port=chrome.port, interval_ms=1000)
    bridge, service = build_stack(chrome, pool, config)

    report = await service.scan_once()

    assert report["ok"] is True
    assert report["scanned"] == 4
    assert report["matched"] == 2
    assert pool_ids(pool) == ["AAA", "BBB"]
    assert bridge.primary_links and bridge.primary_links[0].endswith("/AAA")
    assert bridge.status_emissions > 0
    assert any("2 matched" in m for m, _l in bridge.logs)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_endpoint_new_tab_is_linked_on_the_next_pass(chrome):
    chrome.set_pages(("AAA", ARENA + "one"))
    pool = PagePool()
    config = AutoConnectConfig(url_pattern="arena.ai", host="127.0.0.1", port=chrome.port, interval_ms=1000)
    bridge, service = build_stack(chrome, pool, config)
    scheduler = ScanScheduler(service, watcher_factory=lambda: None)

    task = asyncio.ensure_future(scheduler.run())
    await asyncio.sleep(0.2)
    assert pool_ids(pool) == ["AAA"]

    chrome.set_pages(("AAA", ARENA + "one"), ("BBB", ARENA + "two"))
    await asyncio.sleep(1.4)  # next periodic pass (interval floor is 1s) confirms + finds it
    assert pool_ids(pool) == ["AAA", "BBB"]
    assert len(bridge.pool_links) == 2  # AAA dialled once, never re-dialled
    assert bridge.status_emissions >= 2  # the UI is told about every pool change

    chrome.set_pages(("BBB", ARENA + "two"))  # AAA closed
    await asyncio.sleep(1.4)
    assert pool_ids(pool) == ["BBB"]

    await scheduler.stop()
    assert task.done()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_closed_port_reports_broken_not_empty(chrome):
    pool = PagePool()
    config = AutoConnectConfig(url_pattern="arena.ai", host="127.0.0.1", port=chrome.port, interval_ms=1000)
    bridge, service = build_stack(chrome, pool, config)
    chrome.stop()  # the debug port goes away — Chrome closed

    report = await service.scan_once()

    assert report["ok"] is False
    assert report["error"]
    assert report["matched"] == 0
    assert pool_ids(pool) == []
    assert any(lvl == "warn" and "scan failed" in m for m, lvl in bridge.logs)
