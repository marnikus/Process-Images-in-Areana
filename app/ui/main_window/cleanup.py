from __future__ import annotations
import asyncio
from typing import Any

def _drop_main_client(client, bg_loop):
    try:
        if bg_loop is not None and bg_loop.is_running():
            try:
                fut = asyncio.run_coroutine_threadsafe(client.disconnect(), bg_loop)
                fut.result(timeout=1.0)
            except Exception:
                _sync_drop_client(client)
        else:
            _sync_drop_client(client)
    except Exception:
        _sync_drop_client(client)

def _drop_pool_sockets(pool, bg_loop):
    try:
        tab_ids = list(getattr(pool, "_pages", {}).keys())
        for tid in tab_ids:
            try:
                _drop_one_pooled_tab(pool, tid, bg_loop)
            except Exception:
                continue
        try:
            pool._pages.clear()
            pool._clients.clear()
            pool._controllers.clear()
        except Exception:
            pass
    except Exception:
        pass

def _drop_one_pooled_tab(pool, tab_id, bg_loop):
    try:
        client, ctrl = pool.get_clients(tab_id)
        if client is None:
            return
        if bg_loop is not None and bg_loop.is_running():
            _run_pool_tab_cleanup_sync(pool, tab_id, bg_loop)
        else:
            _sync_drop_client(client)
    except Exception:
        pass

def _run_pool_tab_cleanup_sync(pool, tab_id, bg_loop):
    try:
        import asyncio
        client, ctrl = pool.get_clients(tab_id)
        if client is None:
            return
        coro = _clean_pool_tab(client, ctrl, tab_id)
        fut = asyncio.run_coroutine_threadsafe(coro, bg_loop)
        try:
            fut.result(timeout=1.5)
        except Exception:
            _sync_drop_client(client)
    except Exception:
        try:
            client, _ = pool.get_clients(tab_id)
            _sync_drop_client(client)
        except Exception:
            pass

async def _clean_pool_tab(client, ctrl, tab_id):
    try:
        await _clear_badge_async(client, tab_id)
        await _hide_overlay_async(client, ctrl)
        await _reload_tab_async(client)
    finally:
        await _disconnect_client_async(client)

async def _clear_badge_async(client, tab_id):
    try:
        from app.services.live.worker_badges import clear_badge
        await clear_badge(client, tab_id)
    except Exception:
        pass

async def _hide_overlay_async(client, ctrl):
    try:
        if ctrl and hasattr(ctrl, "hide_watcher_overlay"):
            await ctrl.hide_watcher_overlay()
    except Exception:
        pass
    try:
        await client.send("Runtime.evaluate", {"expression": "document.getElementById('arena-watcher-overlay')?.remove(); document.getElementById('arena-watcher-style-v2')?.remove(); true"})
    except Exception:
        pass

async def _reload_tab_async(client):
    try:
        await client.send("Page.reload")
    except Exception:
        try:
            await client.evaluate("window.location.reload(); true")
        except Exception:
            pass
    try:
        import asyncio
        await asyncio.sleep(0.2)
    except Exception:
        pass

async def _disconnect_client_async(client):
    try:
        await client.disconnect()
    except Exception:
        _sync_drop_client(client)

def _sync_drop_client(client):
    if not client:
        return
    try:
        client._ws = None
        client._connected = False
        rt = getattr(client, "_receive_task", None)
        if rt:
            try:
                rt.cancel()
            except Exception:
                pass
        client._receive_task = None
    except Exception:
        pass

def _drop_browser_sockets(window):
    try:
        pool = getattr(getattr(window, "bridge", None), "_page_pool", None)
        bg_loop = getattr(getattr(window, "bridge", None), "_bg_loop", None)
        if pool is not None:
            _drop_pool_sockets(pool, bg_loop)
        client = getattr(window, "cdp_client", None)
        if client:
            _drop_main_client(client, bg_loop)
    except Exception:
        pass
