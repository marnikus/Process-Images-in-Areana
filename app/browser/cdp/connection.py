"""CDP websocket connection lifecycle (W2 split from cdp_client).

connect/_connect_inner split into phases: candidate URLs, per-candidate
websocket bring-up, domain enables, and lock/loop management.
"""
from __future__ import annotations

import asyncio
import re

log = __import__("logging").getLogger("arena")


def ws_tab_id(ws_url: str) -> str:
    """Tab id from a ws://.../devtools/page/<id> URL ('' when absent)."""
    try:
        m = re.search(r'/devtools/page/([^/]+)$', ws_url)
        return m.group(1) if m else ""
    except Exception:
        return ""


def ws_candidates(ws_url: str, tab_id: str, host: str, port: int) -> list:
    """Ordered unique websocket URLs to try for one logical tab."""
    candidates = [ws_url]
    norm = _norm(ws_url, host, port)
    if norm != ws_url:
        candidates.append(norm)
    candidates += _host_swaps(ws_url, host, port)
    if tab_id:
        candidates += [
            f"ws://{host}:{port}/devtools/page/{tab_id}",
            f"ws://127.0.0.1:{port}/devtools/page/{tab_id}",
            f"ws://localhost:{port}/devtools/page/{tab_id}",
        ]
    seen, uniq = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _host_swaps(ws_url: str, host: str, port: int) -> list:
    """127.0.0.1 <-> localhost variants of a ws URL."""
    swaps = []
    if "127.0.0.1" in ws_url:
        swaps.append(ws_url.replace("127.0.0.1", "localhost"))
        swaps.append(_norm(ws_url.replace("127.0.0.1", "localhost"), host, port))
    if "localhost" in ws_url:
        swaps.append(ws_url.replace("localhost", "127.0.0.1"))
        swaps.append(_norm(ws_url.replace("localhost", "127.0.0.1"), host, port))
    return swaps


def _norm(ws_url: str, host: str, port: int) -> str:
    from ..cdp_protocol import normalize_ws_url
    return normalize_ws_url(ws_url, host, port)


class CdpConnectionMixin:
    """connect()/disconnect() with per-loop locking and candidate retries."""

    def _get_connect_lock(self):
        """Return an asyncio.Lock bound to current running loop, recreating if loop changed."""
        loop = _running_loop()
        if self._connect_lock is None:
            try:
                self._connect_lock = asyncio.Lock()
            except Exception:
                self._connect_lock = None
            return self._connect_lock
        if _lock_loop_mismatch(self._connect_lock, loop):
            log.info(f"CDP lock bound to different loop, recreating")
            self._connect_lock = asyncio.Lock()
        return self._connect_lock

    async def connect(self, ws_url: str) -> bool:
        # Prevent concurrent connects — use asyncio.Lock per-loop and reuse if same tab
        lock = self._get_connect_lock()
        if self._same_tab_connected(ws_url):
            log.info(f"CDP already connected to {ws_url[:80]}, reusing")
            return True
        if not lock:
            return await self._connect_inner(ws_url)
        try:
            async with lock:
                return await self._connect_inner(ws_url)
        except RuntimeError as e:
            return await self._connect_after_lock_error(ws_url, e)

    async def _connect_after_lock_error(self, ws_url: str, err: RuntimeError) -> bool:
        """Handle 'bound to a different event loop': recreate lock once, then direct."""
        if "different event loop" not in str(err) and "bound to a different" not in str(err):
            raise err
        log.warning(f"CDP lock loop mismatch, recreating: {err}")
        try:
            self._connect_lock = asyncio.Lock()
            async with self._connect_lock:
                return await self._connect_inner(ws_url)
        except RuntimeError as e2:
            log.warning(f"CDP lock still mismatched after recreate: {e2}, falling back to direct connect")
            return await self._connect_inner(ws_url)

    def _same_tab_connected(self, ws_url: str) -> bool:
        """True when already connected to this exact tab."""
        try:
            return bool(
                self.is_connected and self._current_ws_url and ws_url
                and self._current_tab_id and ws_tab_id(ws_url) == self._current_tab_id
            )
        except Exception:
            return False

    async def _connect_inner(self, ws_url: str) -> bool:
        if await self._wait_connecting_done():
            return True
        if self._same_tab_connected(ws_url):
            log.info(f"CDP already connected to {ws_url[:80]} inside inner, reusing")
            return True
        self._connecting = True
        try:
            await self.disconnect()
            tab_id = ws_tab_id(ws_url)
            self._current_tab_id = tab_id
            return await self._try_candidates(ws_candidates(ws_url, tab_id, self._host, self._port), ws_url)
        finally:
            self._connecting = False

    async def _wait_connecting_done(self) -> bool:
        """True when a concurrent connect already brought the link up."""
        if not self._connecting:
            return False
        log.info("CDP connect already in progress, waiting")
        for _ in range(10):
            await asyncio.sleep(0.2)
            if self.is_connected:
                return True
        return False

    async def _try_candidates(self, candidates: list, ws_url: str) -> bool:
        """Try each candidate ws URL; report failure when all fail."""
        err = _require_websockets()
        if err:
            log.error(err)
            self.error.emit(err)
            return False
        last_exc = None
        for cand in candidates:
            try:
                return await self._connect_one(cand)
            except ImportError as e:
                last_exc = e
                msg = f"Missing websockets: {e} — pip install websockets aiohttp"
                log.error(msg)
                self.error.emit(msg)
                return False
            except Exception as e:
                last_exc = e
                log.warning(f"CDP connect try {cand[:120]} failed: {e}")
                await self._close_failed_ws()
        self._emit_connect_failed(ws_url, candidates, last_exc)
        return False

    async def _connect_one(self, cand: str) -> bool:
        """Bring up one websocket: connect, receive task, domain enables, emit."""
        import websockets
        self._ws = await websockets.connect(
            cand,
            max_size=50 * 1024 * 1024,
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

    async def _close_failed_ws(self) -> None:
        """Close a half-open websocket after a failed candidate attempt."""
        if not self._ws:
            return
        try:
            await self._ws.close()
        except Exception:
            pass
        self._ws = None

    def _emit_connect_failed(self, ws_url: str, candidates: list, last_exc) -> None:
        """Log + emit the all-candidates-failed error."""
        _connect_failed_error(ws_url, candidates, last_exc, self.error.emit)


def _running_loop():
    """Current running loop, or None outside a coroutine."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _lock_loop_mismatch(lock, loop) -> bool:
    """True when lock is bound to a different loop than the current one."""
    try:
        # In Python 3.10+, Lock._loop is None until first acquire, then set
        lock_loop = getattr(lock, '_loop', None)
        if lock_loop is not None and loop is not None and lock_loop is not loop:
            return True
    except Exception:
        pass
    try:
        # Python 3.11+: private _get_loop
        if hasattr(lock, '_get_loop'):
            lock_loop = lock._get_loop()
            if lock_loop is not None and loop is not None and lock_loop is not loop:
                return True
    except Exception:
        pass
    return False


def _require_websockets() -> str:
    """'' when websockets is importable, else an install-hint error."""
    try:
        import websockets  # noqa: F401
        return ""
    except ImportError as e:
        return (f"❌ Missing dependency 'websockets' — required for Chrome CDP connection. "
                f"Install with: pip install websockets aiohttp\nOriginal error: {e}\n"
                f"Current Python: {__import__('sys').executable}")


def _connect_failed_error(ws_url: str, candidates: list, last_exc, emit) -> None:
    """Log + emit the all-candidates-failed error."""
    err = f"Connect failed for {ws_url[:120]} tried {candidates} last={last_exc}"
    if last_exc and isinstance(last_exc, ModuleNotFoundError):
        err += "\n💡 Fix: pip install websockets aiohttp — then restart app"
    log.error(err)
    emit(err)
