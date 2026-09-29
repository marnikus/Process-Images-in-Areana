from __future__ import annotations
import asyncio
import logging
from ..liveness import note_timed_out
from ..home_loop import on_home_loop, running_loop

log = logging.getLogger("arena")

def _is_expected_close(exc: BaseException) -> bool:
    try:
        name = type(exc).__name__
        txt = str(exc).lower()
        if "closed" in name.lower() or "close" in name.lower():
            return True
        if "no close frame" in txt or "connectionclosed" in txt:
            return True
    except Exception:
        pass
    return False

@on_home_loop
async def _disconnect(transport) -> None:
    transport._connected = False
    _fail_pending(transport, "CDP disconnected")
    ws, transport._ws = transport._ws, None
    task = transport._receive_task
    transport._receive_task = None
    if task:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=0.5)
        except Exception:
            pass
    if ws:
        try:
            await ws.close()
        except Exception:
            pass
    try:
        transport.disconnected.emit()
    except Exception:
        pass

def _receive_teardown(transport) -> bool:
    was = transport._connected
    transport._connected = False
    transport._ws = None
    _fail_pending(transport, "CDP connection lost")
    return was

def _fail_pending(transport, reason: str) -> None:
    pending, transport._pending = transport._pending, {}
    for fut in pending.values():
        _fail_on_its_loop(fut, ConnectionError(reason))

def _fail_on_its_loop(fut, exc: Exception) -> None:
    try:
        loop = fut.get_loop()
        if loop is running_loop():
            _set_exception_if_pending(fut, exc)
        else:
            loop.call_soon_threadsafe(_set_exception_if_pending, fut, exc)
    except RuntimeError:
        pass

def _set_exception_if_pending(fut, exc: Exception) -> None:
    if not fut.done():
        fut.set_exception(exc)

def _receive_error(transport, e: Exception) -> None:
    if _is_expected_close(e):
        log.info(f"CDP receive closed {transport._current_ws_url[:80]}: {e}")
        return
    import traceback
    tb = traceback.format_exc()[-800:]
    log.error(f"CDP receive error {transport._current_ws_url[:80]}: {e} — {tb}")
    try:
        transport.error.emit(f"CDP receive error: {e}")
    except Exception:
        pass
