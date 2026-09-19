"""In-process Chrome DevTools stubs (W2): websocket + HTTP, no real Chrome.

CdpStubServer speaks enough CDP over a real websocket for CDPClient
connect/send/evaluate/DOM flows. CdpHttpStub serves /json/list and
/json/version over plain HTTP for fetch_tabs_sync/diagnose_sync.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STUB_TABS = [
    {"id": "tab-1", "type": "page", "title": "Arena", "url": "https://arena.ai/",
     "webSocketDebuggerUrl": "ws://STUB/devtools/page/tab-1"},
    {"id": "tab-2", "type": "page", "title": "Docs", "url": "https://example.com/",
     "webSocketDebuggerUrl": "ws://STUB/devtools/page/tab-2"},
]


class CdpStubServer:
    """Minimal CDP websocket server bound to an ephemeral 127.0.0.1 port."""

    def __init__(self, tabs=None, mute=False):
        self.tabs = tabs if tabs is not None else STUB_TABS
        # mute: never reply to these methods (timeout tests); enables still
        # answer so connect() stays fast.
        self.mute_methods = {"Runtime.evaluate"} if mute else set()
        self.received: list = []  # every decoded command
        self.server = None
        self.port = 0
        self._clients = set()

    async def start(self):
        from websockets.asyncio.server import serve
        self.server = await serve(self._handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        for ws in list(self._clients):
            try:
                await ws.close()
            except Exception:
                pass
        self.server.close()
        await self.server.wait_closed()

    @property
    def page_ws_url(self) -> str:
        first_page = next(t for t in self.tabs if t.get("type") == "page")
        return f"ws://127.0.0.1:{self.port}/devtools/page/{first_page['id']}"

    async def _handler(self, ws):
        self._clients.add(ws)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                self.received.append(msg)
                if "id" in msg and msg.get("method") not in self.mute_methods:
                    await ws.send(json.dumps(self._reply(msg)))
        finally:
            self._clients.discard(ws)

    def _reply(self, msg: dict) -> dict:
        method = msg.get("method", "")
        if method == "Runtime.evaluate":
            value = {"found": True, "rect": {"x": 1, "y": 2, "width": 3, "height": 4}}
            return {"id": msg["id"], "result": {"result": {"type": "object", "value": value}}}
        if method == "DOM.getDocument":
            return {"id": msg["id"], "result": {"root": {"nodeId": 1, "nodeName": "document"}}}
        if method == "DOM.querySelector":
            found = 7 if "file" in msg.get("params", {}).get("selector", "") else 0
            return {"id": msg["id"], "result": {"nodeId": found}}
        if method == "DOM.setFileInputFiles":
            return {"id": msg["id"], "result": {"files": msg.get("params", {}).get("files", [])}}
        return {"id": msg["id"], "result": {}}

    def methods(self) -> list:
        return [m.get("method") for m in self.received if "method" in m]


class CdpHttpStub:
    """HTTP server stubbing Chrome's /json/list + /json/version endpoints."""

    def __init__(self, tabs=None, extra_paths=None):
        self.tabs = tabs if tabs is not None else STUB_TABS
        self.extra_paths = extra_paths or {}
        self.httpd = None
        self.port = 0
        self._thread = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/json/list":
                    body = json.dumps(outer.tabs).encode("utf-8")
                elif self.path == "/json/version":
                    body = json.dumps({"Browser": "Chrome/stub", "webSocketDebuggerUrl": "ws://stub"}).encode("utf-8")
                elif self.path in outer.extra_paths:
                    body = outer.extra_paths[self.path]
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self._handler_cls = Handler

    def start(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_cls)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
