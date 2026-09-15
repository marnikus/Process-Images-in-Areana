"""CDP Client for Arena — connects to Chrome remote debugging port."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

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

    async def fetch_tabs(self):
        """Fetch tabs via HTTP /json/list"""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/json/list", timeout=aiohttp.ClientTimeout(total=5)) as r:
                    if r.status != 200:
                        return []
                    items = await r.json()
                    tabs = []
                    for item in items:
                        if item.get("type") == "page":
                            tabs.append(TabInfo(
                                id=item.get("id",""),
                                title=item.get("title",""),
                                url=item.get("url",""),
                                ws_url=item.get("webSocketDebuggerUrl",""),
                                type=item.get("type","page")
                            ))
                    return tabs
        except Exception as e:
            log.warning(f"fetch_tabs failed: {e}")
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
            # enable domains
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
            self.error.emit(str(e))
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
            import websockets
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except Exception:
                    continue
                mid = data.get("id")
                if mid and mid in self._pending:
                    self._pending.pop(mid).set_result(data)
                # events ignored for now
        except (asyncio.CancelledError,):
            pass
        except Exception as e:
            log.error(f"CDP receive error: {e}")
        finally:
            self._connected = False
            self.disconnected.emit()

    async def evaluate(self, expression: str):
        """Evaluate JS expression and return value"""
        try:
            r = await self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
            return r.get("result", {}).get("result", {}).get("value")
        except Exception as e:
            log.warning(f"evaluate failed: {e}")
            return None

    async def highlight_element(self, selector: str, color: str = "#FF0000", duration_ms: int = 2000, caption: str = ""):
        """Draw rect highlight overlay via JS, similar to old dom_highlight"""
        # JS that creates overlay div with fixed position
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
