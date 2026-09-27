"""Repair an unanswered CDP session without destroying its generated image.

One bounded attempt per outage, exact remembered endpoint only. Never replay a
caller expression: it might submit a prompt. Only the harmless health ping is
retried. The normal output/JOB-ID verification remains the download authority.
"""
from __future__ import annotations

import asyncio
import logging

from . import connect
from .dialogs import close_open_dialog

log = logging.getLogger("arena")
REPAIR_TIMEOUT_S = 8.0


async def ping(cdp, timeout: float = 3.0) -> bool:
    """A protocol error or empty reply is not a working JavaScript context."""
    await close_open_dialog(cdp)
    try:
        reply = await cdp.send("Runtime.evaluate", {"expression": "1", "returnByValue": True},
                               timeout=timeout)
    except Exception:
        return False
    result = reply.get("result", {})
    return (not reply.get("error") and not result.get("exceptionDetails")
            and result.get("result", {}).get("value") == 1)


def _report(cdp, message: str) -> None:
    """Use the same per-client UI reporter as blocking-dialog recovery."""
    try:
        cdp.dialogs.report(message)
    except Exception:
        log.warning(message)


async def _replace_session(cdp, url: str) -> bool:
    """Caller owns connection lock; clean up partial setup even on cancellation."""
    ready = False
    try:
        await cdp.disconnect()
        cdp.dialogs.open = {}
        ws = await connect._create_ws_connection(url)
        await connect._setup_connected_transport(cdp, url, ws)
        ready = await ping(cdp)
        return ready
    finally:
        if not ready:
            await cdp.disconnect()


async def repair_stalled_session(cdp, failed_socket) -> bool:
    """Share one repair between Watcher/job callers; never search other tabs/ports."""
    url = getattr(cdp, "_current_ws_url", "")
    if not url or not hasattr(cdp, "_connect_lock"):
        return False
    lock = connect._get_connect_lock(cdp)
    async with lock:
        if cdp._ws is not failed_socket:
            return await ping(cdp)
        if getattr(cdp, "_stalled_repair_attempted", False):
            return False
        cdp._stalled_repair_attempted = True
        return await _bounded_repair(cdp, url)


async def _bounded_repair(cdp, url: str) -> bool:
    """Bound socket open + domain setup + health check as a single operation."""
    _report(cdp, "🔌 CDP not answering — reconnecting to the same tab (no reload or resubmit)")
    try:
        ready = await asyncio.wait_for(_replace_session(cdp, url), REPAIR_TIMEOUT_S)
    except Exception as exc:
        _report(cdp, f"⚠ CDP same-tab repair failed: {type(exc).__name__}")
        return False
    note = "✅ CDP response restored — continuing image verification" if ready else (
        "⚠ CDP same-tab repair did not restore page responses — keeping output unverified")
    _report(cdp, note)
    return ready
