"""CDP connect — candidate building + WebSocket connect (C2).

RULE18: file 150-300, func ≤20, CC≤10, methods≤15.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import List

from .tabs import _normalize_ws_url

log = logging.getLogger("arena")


def _extract_tab_id(ws_url: str) -> str:
    try:
        m = re.search(r"/devtools/page/([^/]+)$", ws_url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _build_candidate_urls(ws_url: str, host: str, port: int, tab_id: str) -> List[str]:
    cands: List[str] = []
    cands.append(ws_url)
    norm = _normalize_ws_url(ws_url, host, port)
    if norm != ws_url:
        cands.append(norm)
    if "127.0.0.1" in ws_url:
        cands.append(ws_url.replace("127.0.0.1", "localhost"))
        cands.append(_normalize_ws_url(ws_url.replace("127.0.0.1", "localhost"), host, port))
    if "localhost" in ws_url:
        cands.append(ws_url.replace("localhost", "127.0.0.1"))
        cands.append(_normalize_ws_url(ws_url.replace("localhost", "127.0.0.1"), host, port))
    if tab_id:
        cands.append(f"ws://{host}:{port}/devtools/page/{tab_id}")
        cands.append(f"ws://127.0.0.1:{port}/devtools/page/{tab_id}")
        cands.append(f"ws://localhost:{port}/devtools/page/{tab_id}")
    return cands


def _dedupe_candidates(cands: List[str]) -> List[str]:
    seen = set()
    uniq = []
    for c in cands:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _get_running_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _ensure_lock_exists(transport):
    if transport._connect_lock is None:
        try:
            transport._connect_lock = asyncio.Lock()
        except Exception:
            transport._connect_lock = None
    return transport._connect_lock


def _is_loop_mismatch(lock, loop) -> bool:
    if lock is None or loop is None:
        return False
    try:
        lock_loop = getattr(lock, "_loop", None)
        if lock_loop is not None and lock_loop is not loop:
            return True
    except Exception:
        pass
    try:
        if hasattr(lock, "_get_loop"):
            ll = lock._get_loop()
            if ll is not None and ll is not loop:
                return True
    except Exception:
        pass
    return False


def _get_connect_lock(transport):
    loop = _get_running_loop()
    lock = _ensure_lock_exists(transport)
    if lock is None:
        return None
    if _is_loop_mismatch(lock, loop):
        log.info("CDP lock loop mismatch, recreating")
        try:
            transport._connect_lock = asyncio.Lock()
        except Exception:
            pass
    return transport._connect_lock


async def _enable_cdp_domains(transport):
    for dom in ("Page", "DOM", "Runtime", "Network"):
        try:
            await transport.send(f"{dom}.enable", timeout=10)
        except Exception as e:
            log.debug(f"Enable {dom} failed: {e}")


async def _create_ws_connection(cand: str):
    import websockets
    return await websockets.connect(
        cand,
        max_size=50 * 1024 * 1024,
        open_timeout=10,
        close_timeout=5,
        ping_interval=None,
        ping_timeout=None,
    )


async def _setup_connected_transport(transport, cand: str, ws):
    transport._ws = ws
    transport._connected = True
    transport._current_ws_url = cand
    transport._receive_task = asyncio.create_task(transport._receive_loop())
    await _enable_cdp_domains(transport)
    log.info(f"CDP connected: {cand[:120]}")
    transport.connected.emit()


async def _cleanup_failed_ws(transport):
    if transport._ws:
        try:
            await transport._ws.close()
        except Exception:
            pass
        transport._ws = None


async def _attempt_single_connect(transport, cand: str) -> bool:
    try:
        import websockets  # noqa: F401
    except ImportError as e:
        err = f"Missing websockets: {e} — pip install websockets aiohttp"
        log.error(err)
        transport.error.emit(err)
        return False
    try:
        ws = await _create_ws_connection(cand)
        await _setup_connected_transport(transport, cand, ws)
        return True
    except Exception as e:
        log.warning(f"CDP connect try {cand[:120]} failed: {e}")
        await _cleanup_failed_ws(transport)
        transport._last_exc = e
        return False


async def _try_candidates_loop(transport, candidates: List[str]) -> bool:
    for cand in candidates:
        ok = await _attempt_single_connect(transport, cand)
        if ok:
            return True
    return False


async def _prepare_connect(transport, ws_url: str) -> tuple[str, List[str]]:
    tab_id = _extract_tab_id(ws_url)
    transport._current_tab_id = tab_id
    cands = _build_candidate_urls(ws_url, transport._host, transport._port, tab_id)
    uniq = _dedupe_candidates(cands)
    return tab_id, uniq


async def _wait_if_connecting(transport) -> bool:
    if not getattr(transport, "_connecting", False):
        return False
    log.info("CDP connect already in progress, waiting")
    for _ in range(10):
        await asyncio.sleep(0.2)
        if transport.is_connected:
            return True
    return False


def _is_same_tab_connected(transport, ws_url: str) -> bool:
    try:
        if transport.is_connected and transport._current_tab_id:
            m = re.search(r"/devtools/page/([^/]+)$", ws_url)
            if m and m.group(1) == transport._current_tab_id:
                return True
    except Exception:
        pass
    return False


async def _handle_failed_connect(transport, ws_url: str, candidates: List[str]) -> bool:
    last = getattr(transport, "_last_exc", None)
    err = f"Connect failed for {ws_url[:120]} tried {candidates} last={last}"
    if last and isinstance(last, ModuleNotFoundError):
        err += "\n💡 Fix: pip install websockets aiohttp"
    log.error(err)
    transport.error.emit(err)
    return False


async def _connect_inner(transport, ws_url: str) -> bool:
    if await _wait_if_connecting(transport):
        return True
    if _is_same_tab_connected(transport, ws_url):
        log.info(f"CDP already connected to {ws_url[:80]}, reusing inside inner")
        return True
    transport._connecting = True
    try:
        await transport.disconnect()
        _, candidates = await _prepare_connect(transport, ws_url)
        try:
            import websockets  # noqa: F401
        except ImportError as e:
            err = f"Missing websockets: {e} — pip install websockets aiohttp"
            log.error(err)
            transport.error.emit(err)
            return False
        ok = await _try_candidates_loop(transport, candidates)
        if ok:
            return True
        return await _handle_failed_connect(transport, ws_url, candidates)
    finally:
        transport._connecting = False


def _should_reuse_existing(transport, ws_url: str) -> bool:
    try:
        if transport.is_connected and transport._current_ws_url and ws_url and transport._current_tab_id:
            m = re.search(r"/devtools/page/([^/]+)$", ws_url)
            if m and m.group(1) == transport._current_tab_id:
                return True
    except Exception:
        pass
    return False


async def _connect_with_lock_guarded(transport, ws_url: str, lock) -> bool:
    async with lock:
        return await _connect_inner(transport, ws_url)


async def _handle_lock_mismatch_retry(transport, ws_url: str, exc: RuntimeError) -> bool:
    if "different event loop" not in str(exc) and "bound to a different" not in str(exc):
        raise exc
    log.warning(f"CDP lock loop mismatch, recreating: {exc}")
    try:
        transport._connect_lock = asyncio.Lock()
        async with transport._connect_lock:
            return await _connect_inner(transport, ws_url)
    except RuntimeError as e2:
        log.warning(f"CDP lock still mismatched: {e2}, direct connect")
        return await _connect_inner(transport, ws_url)


async def connect_with_lock(transport, ws_url: str) -> bool:
    if _should_reuse_existing(transport, ws_url):
        log.info(f"CDP already connected to {ws_url[:80]}, reusing")
        return True
    lock = _get_connect_lock(transport)
    if lock is None:
        return await _connect_inner(transport, ws_url)
    try:
        return await _connect_with_lock_guarded(transport, ws_url, lock)
    except RuntimeError as e:
        return await _handle_lock_mismatch_retry(transport, ws_url, e)
