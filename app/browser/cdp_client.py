"""CDP Client for Arena — connects to Chrome remote debugging port.

Robust version: tries multiple hosts, sync fallback via urllib, detailed diagnostics,
and works even when asyncio loop is not running (uses threadpool for sync).
"""

import asyncio
import json
import logging
import socket
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any, List, Tuple

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

log = logging.getLogger("arena")

@dataclass
class TabInfo:
    id: str
    title: str
    url: str
    ws_url: str
    type: str = "page"

# Candidate hosts to try when 127.0.0.1 fails (WSL -> Windows host, etc.)
CANDIDATE_HOSTS = [
    "127.0.0.1",
    "localhost",
    "host.docker.internal",
    "host.containers.internal",
]

def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def _fetch_json_sync(url: str, timeout: float = 3.0) -> Tuple[Any, str]:
    """Synchronous fetch via urllib, returns (data, error)."""
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

def _parse_tabs(items: List[dict]) -> List[TabInfo]:
    tabs = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        # Old Chrome may have type page but no ws url yet; still include if url exists
        t = item.get("type", "")
        if t and t != "page":
            continue
        ws_url = item.get("webSocketDebuggerUrl") or item.get("webSocketDebuggerUrl") or ""
        # Some versions use webSocketDebuggerUrl, some may have it empty for non-page
        # Keep even if ws_url empty? For listing we need ws_url to connect, but for diagnostics keep all
        if not item.get("url"):
            continue
        tabs.append(TabInfo(
            id=item.get("id",""),
            title=item.get("title",""),
            url=item.get("url",""),
            ws_url=ws_url,
            type=item.get("type","page")
        ))
    return tabs

def fetch_tabs_sync(host: str = "127.0.0.1", port: int = 9222, timeout: float = 3.0) -> Tuple[List[TabInfo], str, List[str]]:
    """Try to fetch tabs synchronously, trying candidate hosts.
    Returns (tabs, error, tried_urls)
    """
    tried = []
    last_err = ""
    hosts_to_try = [host] + [h for h in CANDIDATE_HOSTS if h != host]
    for h in hosts_to_try:
        url = f"http://{h}:{port}/json/list"
        tried.append(url)
        # quick port check
        if not _is_port_open(h, port, timeout=1.0):
            last_err = f"Port {port} not open on {h} (connection refused) — is Chrome running with --remote-debugging-port={port}?"
            continue
        data, err = _fetch_json_sync(url, timeout=timeout)
        if err:
            last_err = err
            continue
        tabs = _parse_tabs(data)
        # Even if tabs empty, we got a valid response — return it (Chrome running but no pages)
        return tabs, "", tried
    return [], last_err or "No Chrome tabs found — Chrome not responding on any host", tried

def diagnose_sync(host: str = "127.0.0.1", port: int = 9222) -> dict:
    """Full diagnostics: check port open, /json/version, /json/list on all candidate hosts."""
    results = {"host": host, "port": port, "checks": [], "tabs": [], "summary": ""}
    hosts_to_try = [host] + [h for h in CANDIDATE_HOSTS if h != host]
    all_tabs = []
    for h in hosts_to_try:
        check = {"host": h, "port_open": False, "version": None, "version_error": "", "list_count": 0, "list_error": "", "tabs": []}
        check["port_open"] = _is_port_open(h, port, timeout=1.0)
        # version
        v_url = f"http://{h}:{port}/json/version"
        v_data, v_err = _fetch_json_sync(v_url, timeout=2.0)
        if v_err:
            check["version_error"] = v_err
        else:
            check["version"] = v_data
        # list
        l_url = f"http://{h}:{port}/json/list"
        l_data, l_err = _fetch_json_sync(l_url, timeout=3.0)
        if l_err:
            check["list_error"] = l_err
        else:
            tabs = _parse_tabs(l_data)
            check["list_count"] = len(tabs)
            check["tabs"] = [{"title": t.title[:80], "url": t.url, "id": t.id} for t in tabs[:10]]
            all_tabs.extend(tabs)
        results["checks"].append(check)
    results["tabs"] = [{"title": t.title, "url": t.url, "ws_url": t.ws_url, "id": t.id} for t in all_tabs]
    # summary
    open_hosts = [c["host"] for c in results["checks"] if c["port_open"]]
    if not open_hosts:
        results["summary"] = f"❌ Port {port} not open on any host {hosts_to_try}. Chrome not running with --remote-debugging-port={port} --user-data-dir=\"C:\\arena-images-chrome\". Close all Chrome, then run: \"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\" --remote-debugging-port={port} --user-data-dir=\"C:\\arena-images-chrome\""
    else:
        if not all_tabs:
            results["summary"] = f"⚠ Port {port} open on {open_hosts} but /json/list returned 0 tabs. Open a page in the dedicated Chrome window (the one started with --user-data-dir). If you see Chrome window but no tabs, try http://127.0.0.1:{port} in that Chrome to see if DevTools is blocked."
        else:
            results["summary"] = f"✅ Found {len(all_tabs)} tabs on {open_hosts}: " + "; ".join(f"{t.title[:40]} — {t.url}" for t in all_tabs[:3])
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
        self._receive_task = None
        self._connected = False
        self._current_ws_url = ""

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def is_connected(self) -> bool:
        return bool(self._connected and self._ws is not None)

    # ---- sync API used by bridge when asyncio loop not available or for diagnostics ----
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

    # ---- async API (used when QEventLoop running) ----
    async def fetch_tabs(self):
        """Fetch tabs via HTTP /json/list — tries aiohttp first, fallback to sync in thread."""
        # Try aiohttp first
        try:
            import aiohttp
            hosts_to_try = [self._host] + [h for h in CANDIDATE_HOSTS if h != self._host]
            for h in hosts_to_try:
                try:
                    url = f"http://{h}:{self._port}/json/list"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
                            if r.status != 200:
                                continue
                            items = await r.json()
                            tabs = _parse_tabs(items)
                            # If we got response, return even if empty (means Chrome running)
                            # But if empty, try next host? No, return empty with success
                            # To distinguish, check if we got any tabs or if host is primary
                            if tabs or h == self._host:
                                return tabs
                except Exception as e:
                    log.debug(f"fetch_tabs aiohttp {h} failed: {e}")
                    continue
        except ImportError:
            log.debug("aiohttp not available, using sync fallback")
        except Exception as e:
            log.debug(f"aiohttp path failed: {e}")

        # Fallback to sync in threadpool
        try:
            loop = asyncio.get_event_loop()
            tabs, err, tried = await loop.run_in_executor(None, lambda: fetch_tabs_sync(self._host, self._port))
            if err:
                self.error.emit(err)
            return tabs
        except Exception as e:
            log.warning(f"fetch_tabs fallback failed: {e}")
            self.error.emit(str(e))
            return []

    async def connect(self, ws_url: str) -> bool:
        await self.disconnect()
        try:
            import websockets
            self._ws = await websockets.connect(ws_url, max_size=50*1024*1024, open_timeout=10, close_timeout=5)
            self._connected = True
            self._current_ws_url = ws_url
            self._receive_task = asyncio.create_task(self._receive_loop())
            for dom in ("Page", "DOM", "Runtime", "Network"):
                try:
                    await self.send(f"{dom}.enable")
                except Exception:
                    pass
            log.info(f"CDP connected: {ws_url[:80]}")
            self.connected.emit()
            return True
        except Exception as e:
            log.error(f"CDP connect failed: {e}")
            self.error.emit(f"Connect failed {ws_url[:60]}: {e}")
            return False

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

    async def send(self, method: str, params: dict | None = None) -> dict:
        if not self._ws:
            raise ConnectionError("CDP not connected")
        self._cmd_id += 1
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending[self._cmd_id] = fut
        await self._ws.send(json.dumps({"id": self._cmd_id, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, timeout=30)

    async def _receive_loop(self):
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                mid = data.get("id")
                if mid and mid in self._pending:
                    self._pending.pop(mid).set_result(data)
        except (asyncio.CancelledError,):
            pass
        except Exception as e:
            log.error(f"CDP receive error: {e}")
        finally:
            self._connected = False
            self.disconnected.emit()

    async def evaluate(self, expression: str):
        try:
            r = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
            return r.get("result", {}).get("result", {}).get("value")
        except Exception as e:
            log.warning(f"evaluate failed: {e}")
            return None

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
