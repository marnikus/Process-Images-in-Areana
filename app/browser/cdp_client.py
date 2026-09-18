"""CDP Client for Arena — connects to Chrome remote debugging port.

Robust version: tries multiple hosts, sync fallback via urllib, detailed diagnostics,
and works even when asyncio loop is not running (uses threadpool for sync).

Fixes for duplicate tabs and connection stability:
- Deduplicate tabs by id only (not ws_url host variant)
- Normalize ws_url host to configured host for stable connection
- Diagnose deduplicates for summary
- Connect tries: original ws_url, host-swapped variants, and constructed ws://host:port/devtools/page/{id}
- websockets connect uses ping_interval=None to avoid premature disconnect
- Added DOM methods for file input attachment via CDP
"""

import asyncio
import json
import logging
import socket
import urllib.request
import urllib.error
import re
from dataclasses import dataclass
from typing import Any, List, Tuple, Optional

try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    class QObject:
        def __init__(self, *a, **kw): pass
    def Signal(*a, **kw):
        class _Sig:
            def emit(self, *a, **kw): pass
            def connect(self, *a, **kw): pass
        return _Sig()

# Phase 2: pure protocol extracted to cdp_protocol.py — transport stays here
from .cdp_events import CDPEventRouter, route_cdp_message
from .cdp_protocol import (
    TabInfo as _PureTabInfo,
    is_devtools_url as _pure_is_devtools,
    normalize_ws_url as _pure_normalize,
    parse_tabs as _pure_parse_tabs,
    filter_real_tabs as _pure_filter_real,
)

log = logging.getLogger("arena")

@dataclass
class TabInfo:
    id: str
    title: str
    url: str
    ws_url: str
    type: str = "page"

# Only 127.0.0.1 and localhost to avoid DNS freeze
CANDIDATE_HOSTS = [
    "127.0.0.1",
    "localhost",
]

def _is_port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def _fetch_json_sync(url: str, timeout: float = 3.0) -> Tuple[Any, str]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status} for {url}"
            raw = resp.read()
            try:
                data = json.loads(raw.decode("utf-8", errors="ignore"))
                return data, ""
            except Exception as e:
                return None, f"JSON parse failed for {url}: {e}"
    except urllib.error.URLError as e:
        return None, f"URLError {url}: {e.reason if hasattr(e, 'reason') else e}"
    except Exception as e:
        return None, f"Exception {url}: {e}"

# Wrappers delegating to pure protocol (backward compat)
def _normalize_ws_url(ws_url: str, preferred_host: str, preferred_port: int) -> str:
    return _pure_normalize(ws_url, preferred_host, preferred_port)

def _is_devtools_url(url: str, title: str = "") -> bool:
    return _pure_is_devtools(url, title)

def _parse_tabs(items: List[dict], preferred_host: str = "127.0.0.1", preferred_port: int = 9222, include_devtools: bool = True) -> List[TabInfo]:
    pure_tabs = _pure_parse_tabs(items, preferred_host, preferred_port, include_devtools)
    return [TabInfo(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url, type=t.type) for t in pure_tabs]

def _filter_real_tabs(tabs: List[TabInfo]) -> List[TabInfo]:
    pure = [_PureTabInfo(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url, type=t.type) for t in tabs]
    filtered = _pure_filter_real(pure)
    return [TabInfo(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url, type=t.type) for t in filtered]

def fetch_tabs_sync(host: str = "127.0.0.1", port: int = 9222, timeout: float = 3.0) -> Tuple[List[TabInfo], str, List[str]]:
    """Try to fetch tabs synchronously, trying candidate hosts and merging results.
    Returns (tabs, error, tried_urls) — deduplicated by id.
    """
    tried = []
    last_err = ""
    all_tabs_by_id: dict[str, TabInfo] = {}
    hosts_to_try = [host] + [h for h in CANDIDATE_HOSTS if h != host]
    for h in hosts_to_try:
        url = f"http://{h}:{port}/json/list"
        tried.append(url)
        if not _is_port_open(h, port, timeout=1.0):
            last_err = f"Port {port} not open on {h} (connection refused) — is Chrome running with --remote-debugging-port={port}?"
            continue
        data, err = _fetch_json_sync(url, timeout=timeout)
        if err:
            last_err = err
            continue
        tabs = _parse_tabs(data, preferred_host=host, preferred_port=port)
        for t in tabs:
            # Deduplicate by id only — same page via 127.0.0.1 and localhost has same id but different ws_url host
            key = t.id or t.ws_url
            if not key:
                continue
            if key not in all_tabs_by_id:
                all_tabs_by_id[key] = t
            else:
                # Prefer entry with ws_url containing preferred host, or with non-empty ws_url
                existing = all_tabs_by_id[key]
                if not existing.ws_url and t.ws_url:
                    all_tabs_by_id[key] = t
                elif host in t.ws_url and host not in existing.ws_url:
                    all_tabs_by_id[key] = t
    if all_tabs_by_id:
        return list(all_tabs_by_id.values()), "", tried
    return [], last_err or "No Chrome tabs found — Chrome not responding on any host", tried

def diagnose_sync(host: str = "127.0.0.1", port: int = 9222) -> dict:
    """Full diagnostics: check port open, /json/version, /json/list on all candidate hosts."""
    results = {"host": host, "port": port, "checks": [], "tabs": [], "summary": ""}
    hosts_to_try = [host] + [h for h in CANDIDATE_HOSTS if h != host]
    all_tabs_by_id: dict[str, TabInfo] = {}
    for h in hosts_to_try:
        check = {"host": h, "port_open": False, "version": None, "version_error": "", "list_count": 0, "list_error": "", "tabs": []}
        check["port_open"] = _is_port_open(h, port, timeout=1.0)
        v_url = f"http://{h}:{port}/json/version"
        v_data, v_err = _fetch_json_sync(v_url, timeout=2.0)
        if v_err:
            check["version_error"] = v_err
        else:
            check["version"] = v_data
        l_url = f"http://{h}:{port}/json/list"
        l_data, l_err = _fetch_json_sync(l_url, timeout=3.0)
        if l_err:
            check["list_error"] = l_err
        else:
            tabs = _parse_tabs(l_data, preferred_host=host, preferred_port=port)
            check["list_count"] = len(tabs)
            check["tabs"] = [{"title": t.title[:80], "url": t.url, "id": t.id} for t in tabs[:10]]
            for t in tabs:
                key = t.id or t.ws_url
                if key and key not in all_tabs_by_id:
                    all_tabs_by_id[key] = t
        results["checks"].append(check)
    all_tabs = list(all_tabs_by_id.values())
    results["tabs"] = [{"title": t.title, "url": t.url, "ws_url": t.ws_url, "id": t.id} for t in all_tabs]
    open_hosts = [c["host"] for c in results["checks"] if c["port_open"]]
    if not open_hosts:
        results["summary"] = f"❌ Port {port} not open on any host {hosts_to_try}. Chrome not running with --remote-debugging-port={port} --user-data-dir=\"C:\\arena-images-chrome\". Close all Chrome, then run: \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --remote-debugging-port={port} --user-data-dir=\"C:\\arena-images-chrome\""
    else:
        if not all_tabs:
            results["summary"] = f"⚠ Port {port} open on {open_hosts} but /json/list returned 0 tabs. Open a page in the dedicated Chrome window (the one started with --user-data-dir). If you see Chrome window but no tabs, try http://127.0.0.1:{port} in that Chrome to see if DevTools is blocked."
        else:
            # Show unique count, not duplicated
            results["summary"] = f"✅ Found {len(all_tabs)} unique tab(s) on {open_hosts}: " + "; ".join(f"{t.title[:40]} — {t.url}" for t in all_tabs[:3])
    return results

class CDPClient(QObject):
    connected = Signal()
    disconnected = Signal()
    error = Signal(str)

    def __init__(self, host: str = "127.0.0.1", port: int = 9222, parent=None):
        super().__init__(parent)
        self._host = host
        self._port = port
        self._ws = None
        self._cmd_id = 0
        self._pending = {}
        self.events = CDPEventRouter()
        self._receive_task = None
        self._connected = False
        self._current_ws_url = ""
        self._current_tab_id = ""
        self._connect_lock = None
        self._connecting = False

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and self._ws is not None)

    def set_host_port(self, host: str = None, port: int = None):
        if host:
            self._host = str(host).strip() or self._host
        if port:
            try:
                p = int(port)
                if 1 <= p <= 65535:
                    self._port = p
            except Exception:
                pass

    def get_host_port(self):
        return self._host, self._port

    def fetch_tabs_sync(self, host: str = None, port: int = None):
        h = host or self._host
        p = port or self._port
        tabs, err, tried = fetch_tabs_sync(h, p)
        if err:
            log.warning(f"fetch_tabs_sync failed: {err} tried={tried}")
            self.error.emit(err)
        return tabs

    def diagnose_sync(self, host: str = None, port: int = None) -> dict:
        h = host or self._host
        p = port or self._port
        return diagnose_sync(h, p)

    async def fetch_tabs(self):
        """Fetch tabs via HTTP /json/list — tries aiohttp first, merging all hosts, fallback to sync."""
        merged_by_id: dict[str, TabInfo] = {}
        try:
            import aiohttp
            hosts_to_try = [self._host] + [h for h in CANDIDATE_HOSTS if h != self._host]
            for h in hosts_to_try:
                try:
                    url = f"http://{h}:{self._port}/json/list"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as r:
                            if r.status != 200:
                                continue
                            items = await r.json()
                            tabs = _parse_tabs(items, preferred_host=self._host, preferred_port=self._port)
                            for t in tabs:
                                key = t.id or t.ws_url
                                if key and key not in merged_by_id:
                                    merged_by_id[key] = t
                except Exception as e:
                    log.debug(f"fetch_tabs aiohttp {h} failed: {e}")
                    continue
            if merged_by_id:
                return list(merged_by_id.values())
        except ImportError:
            log.debug("aiohttp not available, using sync fallback")
        except Exception as e:
            log.debug(f"aiohttp path failed: {e}")

        try:
            loop = asyncio.get_event_loop()
            tabs, err, tried = await loop.run_in_executor(None, lambda: fetch_tabs_sync(self._host, self._port))
            if err and not tabs:
                self.error.emit(err)
            return tabs
        except Exception as e:
            log.warning(f"fetch_tabs fallback failed: {e}")
            self.error.emit(str(e))
            return []

    def _get_connect_lock(self):
        """Return an asyncio.Lock bound to current running loop, recreating if loop changed."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        # Create if missing
        if self._connect_lock is None:
            try:
                self._connect_lock = asyncio.Lock()
            except Exception:
                self._connect_lock = None
            return self._connect_lock
        # Detect loop mismatch — if lock bound to different loop, recreate
        try:
            # In Python 3.10+, Lock._loop is None until first acquire, then set
            lock_loop = getattr(self._connect_lock, '_loop', None)
            if lock_loop is not None and loop is not None and lock_loop is not loop:
                log.info(f"CDP lock bound to different loop {lock_loop} vs {loop}, recreating")
                self._connect_lock = asyncio.Lock()
        except Exception:
            # If detection fails, try to get loop via private method (Python 3.11+)
            try:
                lock_loop = self._connect_lock._get_loop() if hasattr(self._connect_lock, '_get_loop') else None
                if lock_loop is not None and loop is not None and lock_loop is not loop:
                    self._connect_lock = asyncio.Lock()
            except Exception:
                pass
        return self._connect_lock

    async def connect(self, ws_url: str) -> bool:
        # Prevent concurrent connects — use asyncio.Lock per-loop and reuse if same tab
        # Ensure lock exists and is bound to current loop
        lock = self._get_connect_lock()
        try:
            if self.is_connected and self._current_ws_url and ws_url and self._current_tab_id:
                m = re.search(r'/devtools/page/([^/]+)$', ws_url)
                if m and m.group(1) == self._current_tab_id:
                    log.info(f"CDP already connected to {ws_url[:80]}, reusing")
                    return True
        except Exception:
            pass
        if lock:
            try:
                async with lock:
                    return await self._connect_inner(ws_url)
            except RuntimeError as e:
                # Handle "is bound to a different event loop" — recreate and retry once
                if "different event loop" in str(e) or "bound to a different" in str(e):
                    log.warning(f"CDP lock loop mismatch, recreating: {e}")
                    try:
                        self._connect_lock = asyncio.Lock()
                        async with self._connect_lock:
                            return await self._connect_inner(ws_url)
                    except RuntimeError as e2:
                        log.warning(f"CDP lock still mismatched after recreate: {e2}, falling back to direct connect")
                        return await self._connect_inner(ws_url)
                else:
                    raise
        else:
            return await self._connect_inner(ws_url)

    async def _connect_inner(self, ws_url: str) -> bool:
        if self._connecting:
            log.info("CDP connect already in progress, waiting")
            for _ in range(10):
                await asyncio.sleep(0.2)
                if self.is_connected:
                    return True
        # If already connected to same tab after waiting, reuse
        try:
            if self.is_connected and self._current_tab_id:
                m = re.search(r'/devtools/page/([^/]+)$', ws_url)
                if m and m.group(1) == self._current_tab_id:
                    log.info(f"CDP already connected to {ws_url[:80]} inside inner, reusing")
                    return True
        except Exception:
            pass
        self._connecting = True
        try:
            await self.disconnect()
            tab_id = ""
            try:
                m = re.search(r'/devtools/page/([^/]+)$', ws_url)
                if m:
                    tab_id = m.group(1)
            except Exception:
                pass
            self._current_tab_id = tab_id

            candidates = []
            candidates.append(ws_url)
            norm = _normalize_ws_url(ws_url, self._host, self._port)
            if norm != ws_url:
                candidates.append(norm)
            if "127.0.0.1" in ws_url:
                candidates.append(ws_url.replace("127.0.0.1", "localhost"))
                candidates.append(_normalize_ws_url(ws_url.replace("127.0.0.1", "localhost"), self._host, self._port))
            if "localhost" in ws_url:
                candidates.append(ws_url.replace("localhost", "127.0.0.1"))
                candidates.append(_normalize_ws_url(ws_url.replace("localhost", "127.0.0.1"), self._host, self._port))
            if tab_id:
                candidates.append(f"ws://{self._host}:{self._port}/devtools/page/{tab_id}")
                candidates.append(f"ws://127.0.0.1:{self._port}/devtools/page/{tab_id}")
                candidates.append(f"ws://localhost:{self._port}/devtools/page/{tab_id}")

            seen = set()
            uniq_candidates = []
            for c in candidates:
                if c not in seen:
                    seen.add(c)
                    uniq_candidates.append(c)
            candidates = uniq_candidates

            last_exc = None
            try:
                import websockets
            except ImportError as e:
                err = f"❌ Missing dependency 'websockets' — required for Chrome CDP connection. Install with: pip install websockets aiohttp\nOriginal error: {e}\nCurrent Python: {__import__('sys').executable}"
                log.error(err)
                self.error.emit(err)
                return False

            for cand in candidates:
                try:
                    self._ws = await websockets.connect(
                        cand,
                        max_size=50*1024*1024,
                        open_timeout=10,
                        close_timeout=5,
                        ping_interval=None,
                        ping_timeout=None,
                    )
                    self._connected = True
                    self._current_ws_url = cand
                    self._receive_task = asyncio.create_task(self._receive_loop())
                    for dom in ("Page", "DOM", "Runtime", "Network"):
                        try:
                            await self.send(f"{dom}.enable", timeout=10)
                        except Exception as e:
                            log.debug(f"Enable {dom} failed: {e}")
                    log.info(f"CDP connected: {cand[:120]}")
                    self.connected.emit()
                    return True
                except ImportError as e:
                    last_exc = e
                    err = f"Missing websockets: {e} — pip install websockets aiohttp"
                    log.error(err)
                    self.error.emit(err)
                    return False
                except Exception as e:
                    last_exc = e
                    log.warning(f"CDP connect try {cand[:120]} failed: {e}")
                    if self._ws:
                        try:
                            await self._ws.close()
                        except Exception:
                            pass
                        self._ws = None
                    continue
            err = f"Connect failed for {ws_url[:120]} tried {candidates} last={last_exc}"
            if last_exc and isinstance(last_exc, ModuleNotFoundError):
                err += "\n💡 Fix: pip install websockets aiohttp — then restart app"
            log.error(err)
            self.error.emit(err)
            return False
        finally:
            self._connecting = False

    async def disconnect(self):
        self._connected = False
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except Exception:
                pass
            self._receive_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._pending.clear()
        self.disconnected.emit()

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        if not self._ws:
            raise ConnectionError("CDP not connected")
        self._cmd_id += 1
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending[self._cmd_id] = fut
        payload = json.dumps({"id": self._cmd_id, "method": method, "params": params or {}})
        await self._ws.send(payload)
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(self._cmd_id, None)
            raise TimeoutError(f"CDP command {method} timed out after {timeout}s")

    async def _receive_loop(self):
        try:
            log.info(f"CDP receive loop started for {self._current_ws_url[:80]}")
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                route_cdp_message(self, data)
            log.warning(f"CDP receive loop ended normally for {self._current_ws_url[:80]} — websocket closed by Chrome")
        except asyncio.CancelledError:
            log.info(f"CDP receive loop cancelled for {self._current_ws_url[:80]}")
            pass
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[-800:]
            log.error(f"CDP receive error for {self._current_ws_url[:80]}: {e} — {tb}")
            self.error.emit(f"CDP receive error: {e}")
        finally:
            was_connected = self._connected
            self._connected = False
            if was_connected:
                log.warning(f"CDP disconnected (was connected) for {self._current_ws_url[:80]}")
            else:
                log.info(f"CDP disconnected (was not connected) for {self._current_ws_url[:80]}")
            try:
                self.disconnected.emit()
            except Exception:
                pass

    async def evaluate(self, expression: str, await_promise: bool = True):
        try:
            r = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": await_promise})
            # Check for exception
            res = r.get("result", {})
            if res.get("exceptionDetails"):
                log.warning(f"evaluate exception: {res.get('exceptionDetails')}")
                return None
            return res.get("result", {}).get("value")
        except Exception as e:
            log.warning(f"evaluate failed: {e}")
            return None

    # ---- DOM helpers for file input ----
    async def get_document(self) -> Optional[dict]:
        try:
            r = await self.send("DOM.getDocument", {"depth": 0})
            return r.get("result", {}).get("root")
        except Exception as e:
            log.warning(f"DOM.getDocument failed: {e}")
            return None

    async def query_selector(self, node_id: int, selector: str) -> Optional[int]:
        """Return nodeId of element matching selector under node_id, or None."""
        try:
            r = await self.send("DOM.querySelector", {"nodeId": node_id, "selector": selector})
            return r.get("result", {}).get("nodeId") or None
        except Exception as e:
            log.debug(f"querySelector {selector} failed: {e}")
            return None

    async def query_selector_all(self, node_id: int, selector: str) -> List[int]:
        try:
            r = await self.send("DOM.querySelectorAll", {"nodeId": node_id, "selector": selector})
            return r.get("result", {}).get("nodeIds") or []
        except Exception as e:
            log.debug(f"querySelectorAll {selector} failed: {e}")
            return []

    async def set_file_input_files(self, node_id: int, files: List[str]) -> bool:
        """Set files and reject explicit or malformed protocol failures."""
        try:
            reply = await self.send("DOM.setFileInputFiles", {"nodeId": node_id, "files": files})
            if not isinstance(reply, dict) or reply.get("error"):
                log.warning(f"setFileInputFiles protocol failure for node {node_id}: {reply}")
                return False
            return "result" in reply
        except Exception as e:
            log.warning(f"setFileInputFiles failed for node {node_id} files {files}: {e}")
            return False

    async def attach_image_cdp(self, image_path: str, selectors: List[str] = None) -> tuple[bool, str]:
        """Attach to the active composer; retained as the transport facade."""
        from .attachment_probes import attach_file
        evidence = await attach_file(self, image_path, selectors)
        return evidence.ok, evidence.reason

    async def highlight_element(self, selector: str, color: str = "#FF0000", duration_ms: int = 2000, caption: str = ""):
        js = f"""
(function(){{
  try {{
    var sel = {json.dumps(selector)};
    var el = document.querySelector(sel);
    if (!el) return {{found:false}};
    var r = el.getBoundingClientRect();
    if (!r || (!r.width && !r.height)) return {{found:false}};
    var box = document.createElement('div');
    box.setAttribute('data-arena-highlight','1');
    box.style.cssText = [
      'position:fixed',
      'left:'+Math.max(0,r.left)+'px',
      'top:'+Math.max(0,r.top)+'px',
      'width:'+Math.max(0,r.width)+'px',
      'height:'+Math.max(0,r.height)+'px',
      'outline:2px solid {color}',
      'outline-offset:-1px',
      'background:rgba(255,0,0,0.08)',
      'pointer-events:none',
      'z-index:2147483647'
    ].join(';');
    var tag = document.createElement('div');
    tag.textContent = {json.dumps(caption or selector)};
    tag.style.cssText = [
      'position:absolute','left:0','top:-18px',
      'font:700 11px/14px sans-serif','padding:2px 6px',
      'color:#fff','background:{color}','white-space:nowrap',
      'border-radius:3px'
    ].join(';');
    box.appendChild(tag);
    (document.body||document.documentElement).appendChild(box);
    setTimeout(function(){{ if(box.parentNode) box.parentNode.removeChild(box); }}, {duration_ms});
    return {{found:true, rect:{{x:r.left,y:r.top,width:r.width,height:r.height}}}};
  }} catch(e) {{ return {{found:false, error:String(e)}}; }}
}})()
"""
        return await self.evaluate(js)

    async def clear_highlights(self):
        js = """
(function(){
  try {
    var old = document.querySelectorAll('[data-arena-highlight]');
    var n = old.length;
    for(var i=0;i<old.length;i++){ if(old[i].parentNode) old[i].parentNode.removeChild(old[i]); }
    return {cleared:n};
  } catch(e){ return {cleared:0}; }
})()
"""
        return await self.evaluate(js)
