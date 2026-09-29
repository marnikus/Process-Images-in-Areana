from __future__ import annotations
import asyncio
import time
from typing import Any
from .patches import _get_const

_RECONCILE_WAIT_SEC = 10.0

async def _hold_reconciler(bridge: Any) -> bool:
    wait_sec = _get_const("_RECONCILE_WAIT_SEC", _RECONCILE_WAIT_SEC)
    deadline = time.monotonic() + wait_sec
    while getattr(bridge, "_auto_scan_running", False):
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    bridge._auto_scan_running = True
    return True
