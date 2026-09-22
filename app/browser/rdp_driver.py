"""RDP tab driver — Firefox tabs connect and automate (2026-09-22).

`RdpDriver` is the `CDPTransport`-compatible async driver the bridge and the
pool hold for Firefox tabs: it speaks `rdp://host:port#tab` handles, runs the
sync `rdp.py` client in an executor, and decodes `evaluate` answers to the
CDP value shape (`None` + `last_error[_kind]` on failure) so the arena
controller, badges and watchers work unchanged. No persistent socket —
"connected" means the endpoint answers and the tab resolves, rechecked by
every operation, so a killed Firefox degrades to transport errors instead
of a dead socket.

What RDP cannot do stays honest: `attach_image_cdp` refuses with the named
reason (`⛔ not in RDP`) and `send` raises — every `send` caller is guarded.
"""

import asyncio
import json
import logging
from typing import List, Optional, Tuple
from urllib.parse import urlsplit

from . import rdp
from .cdp.transport import CDPTransport

log = logging.getLogger("arena")

CONNECT_TIMEOUT = 3.0
EVAL_TIMEOUT = 30.0


def parse_handle(ws_url: str) -> Optional[Tuple[str, int, str]]:
    """`rdp://host:port#tab` → (host, port, tab); None when not a handle."""
    try:
        parts = urlsplit((ws_url or "").strip())
        if parts.scheme.lower() != "rdp" or not parts.fragment:
            return None
        host, _, port = parts.netloc.rpartition(":")
        return host or "127.0.0.1", int(port), parts.fragment
    except Exception:
        return None


def _error_kind(err: str) -> str:
    """RDP error text → the CDP `last_error_kind` vocabulary."""
    head = (err or "").split(":", 1)[0].strip()
    if head == "js":
        return "js"
    if head in ("transport", "no-tab", "navigated"):
        return "transport"
    return "protocol"


class RdpDriver(CDPTransport):
    """One Firefox tab: `connect(handle)` + `evaluate` + honest refusals."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, parent=None) -> None:
        super().__init__(host, port, parent)
        self._tab_source = None
        self._last_fetch_errors: list = []

    def set_tab_source(self, source) -> None:
        """Async `fetch_tabs` callable (the multi-browser fetch); None = own endpoint."""
        self._tab_source = source

    @property
    def is_connected(self) -> bool:
        return bool(self._connected)

    def _note(self, kind: str, text: str) -> None:
        """Remember why an op failed (callers only see None/False)."""
        self.last_error_kind = kind
        self.last_error = (text or "")[:300]
        log.warning(f"rdp {kind} error: {self.last_error}")

    async def _run(self, func, *args):
        """Sync `rdp.py` in an executor (never block the loop on TCP)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args))

    async def connect(self, ws_url: str) -> bool:
        """Attach the handle's tab: the endpoint must answer and resolve it."""
        parsed = parse_handle(ws_url)
        if parsed is None:
            self._note("transport", f"not an RDP tab handle: {(ws_url or '')[:80]}")
            return False
        host, port, tab_id = parsed
        self.set_host_port(host, port)
        rows, err = await self._run(rdp.list_tabs, rdp.Endpoint(host, port), CONNECT_TIMEOUT)
        if err or not any(r["id"] == tab_id for r in rows):
            self._note("transport", err or f"no open tab {tab_id!r}")
            return False
        self._current_ws_url, self._current_tab_id = ws_url, tab_id
        self._connected = True
        self.last_error = ""
        self.last_error_kind = ""
        self.connected.emit()
        return True

    async def disconnect(self) -> None:
        """Drop the session (the endpoint's pooled socket stays — reconnecting reuses it)."""
        self._connected = False
        try:
            self.disconnected.emit()
        except Exception:
            pass

    async def evaluate(self, expression: str, await_promise: bool = True):
        """Run JS in the tab; the decoded value, None + `last_error` on failure."""
        _ = await_promise  # RDP always awaits (mapped.await)
        if not self._current_tab_id:
            self._note("transport", "not connected")
            return None
        value, err = await self._run(
            rdp.evaluate, rdp.Endpoint(self._host, self._port),
            self._current_tab_id, expression, EVAL_TIMEOUT)
        if err:
            self._note(_error_kind(err), err)
            return None
        self.last_error = ""
        self.last_error_kind = ""
        return _decode(value)

    async def attach_image_cdp(self, image_path: str, selectors: List[str] = None):
        """Image attach needs CDP `DOM.setFileInputFiles` — named, never silent."""
        _ = (image_path, selectors)
        return False, ("⛔ not in RDP: image attach needs CDP DOM.setFileInputFiles — "
                       "pool a Chrome/Edge tab for attach steps")

    async def send(self, method: str, params: dict | None = None, timeout: float = 30):
        """Raw CDP send does not exist on RDP (every caller is guarded)."""
        _ = (params, timeout)  # signature parity with CDPTransport; always raises
        raise ConnectionError(f"⛔ not in RDP: raw CDP send ({method})")

    def diagnose_sync(self, host: str = None, port: int = None) -> dict:
        """Probe + tab count for a Firefox endpoint (the `diagnose_sync` shape)."""
        host = host or self._host
        try:
            port_i = int(port or self._port)
        except Exception:
            port_i = self._port
        check = {"host": host, "port_open": False, "version": None,
                 "version_error": "", "list_count": 0, "list_error": "", "tabs": []}
        rows, err = rdp.list_tabs(rdp.Endpoint(host, port_i), CONNECT_TIMEOUT)
        if err:
            check["list_error"] = err
            summary = (f"❌ Firefox not reachable on {host}:{port_i} — start it with "
                       f"--start-debugger-server={port_i} (close other Firefox windows first).")
            return {"host": host, "port": port_i, "browser": "firefox",
                    "checks": [check], "tabs": [], "summary": summary}
        check["port_open"] = True
        check["list_count"] = len(rows)
        check["tabs"] = [{"title": r["title"][:80], "url": r["url"], "id": r["id"]} for r in rows[:10]]
        tabs = [{"title": r["title"], "url": r["url"], "id": r["id"], "browser": "firefox",
                 "ws_url": f"rdp://{host}:{port_i}#{r['id']}"} for r in rows]
        sample = "; ".join(f"{r['title'][:40]} — {r['url']}" for r in rows[:3])
        summary = f"✅ Firefox on {host}:{port_i} — {len(rows)} tab(s): {sample}" if rows else \
            f"⚠ Firefox on {host}:{port_i} answers but lists 0 tabs. Open a page in Firefox."
        return {"host": host, "port": port_i, "browser": "firefox",
                "checks": [check], "tabs": tabs, "summary": summary}

    async def fetch_tabs(self):
        """The tab source when set, else this endpoint's own tabs."""
        if self._tab_source is not None:
            tabs, errors = await self._tab_source()
            self._last_fetch_errors = list(errors or [])
            return tabs
        from .cdp.tabs import TabInfo
        rows, _err = await self._run(rdp.list_tabs, rdp.Endpoint(self._host, self._port),
                                     CONNECT_TIMEOUT)
        return [TabInfo(id=r["id"], title=r["title"], url=r["url"],
                        ws_url=f"rdp://{self._host}:{self._port}#{r['id']}",
                        browser="firefox", protocol="rdp") for r in rows]


def _decode(value):
    """RDP JSON-string value → the decoded CDP shape (raw text fallback)."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value
