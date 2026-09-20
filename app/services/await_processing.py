"""AWAIT_PROCESSING_IMAGE — wait only while the page is busy (B12, 2026-10-08).

Before: the block shared `_handle_wait` with WAIT_OUTPUT, i.e. the
*new-output* wait (page overlay "wait for finish generation", pool row
`waiting generation`, revival arming, `timeout_ms` = 120 s). The default
stack puts it BEFORE ATTACH_IMAGE, so on every idle page it waited the whole
120 s: the first run "started without pasting image and prompt and waited for
a generation that never started". Its own selector / match text were never
read (the default selector is Playwright syntax, not CSS).

Now: poll the processing-indicator probe (`app/browser/processing_probe.py`)
— idle page → `success` at once; busy page → `waiting` (overlay + pool row)
until the indicator disappears, the timeout elapses (still `success`: the
block never fails a job) or the run is cancelled (`skipped`).
Imports: browser + services siblings only (never single_job_runner).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Tuple

from app.browser.processing_probe import build_processing_probe, interpret_processing
from app.services.cooldown_service import is_tab_aborted
from app.services.run_state import JobAction

POLL_MS_DEFAULT = 1000
POLL_MS_MIN = 250
POLL_MS_MAX = 5000
TIMEOUT_MS_DEFAULT = 120000
OVERLAY_MESSAGE = "waiting for the running generation to finish"


def _emit(ctx: Any, block: Any, status: str, msg: str) -> None:
    try:
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, status, msg))
    except Exception:
        pass


def _log(ctx: Any, msg: str, level: str = "info") -> None:
    try:
        ctx.bridge._log(f"[{ctx.corr_id}] {msg}", level)
    except Exception:
        pass


def _name(block: Any) -> str:
    return getattr(block, "display_name", "") or getattr(block, "block_id", "AWAIT_PROCESSING_IMAGE")


def poll_seconds(block: Any) -> float:
    """`extra.poll_interval_ms` clamped to [250, 5000] ms, default 1 s."""
    extra = getattr(block, "extra", None) or {}
    try:
        ms = int(extra.get("poll_interval_ms") or POLL_MS_DEFAULT)
    except (TypeError, ValueError):
        ms = POLL_MS_DEFAULT
    return max(POLL_MS_MIN, min(POLL_MS_MAX, ms)) / 1000.0


def timeout_ms(block: Any) -> int:
    """Block timeout; 0/None means the definition default (120 s)."""
    try:
        return int(getattr(block, "timeout_ms", 0) or TIMEOUT_MS_DEFAULT)
    except (TypeError, ValueError):
        return TIMEOUT_MS_DEFAULT


def _cancelled(ctx: Any) -> bool:
    if getattr(ctx.bridge, "_cancel_requested", False):
        return True
    return is_tab_aborted(getattr(ctx.bridge, "_page_pool", None), ctx.tab_id)


async def probe_processing(ctx: Any, block: Any) -> Dict[str, Any]:
    """One probe round trip; a failed evaluate reads as idle (with `error`)."""
    js = build_processing_probe(getattr(block, "selector", "") or "",
                                getattr(block, "match_text", "") or "")
    try:
        raw = await ctx.client.evaluate(js)
    except Exception as e:
        return {"processing": False, "indicators": [], "error": str(e)}
    return interpret_processing(raw)


def describe(res: Dict[str, Any]) -> str:
    """Human line for the indicators the probe saw."""
    bits = []
    for ind in res.get("indicators", [])[:3]:
        kind, sel, text = ind.get("kind", "?"), ind.get("sel", ""), ind.get("text", "")
        bits.append(f"{kind} {sel}" + (f" '{text}'" if text else ""))
    return "; ".join(bits) or "indicator"


def _idle_message(res: Dict[str, Any]) -> str:
    err = res.get("error") or res.get("reason")
    if err:
        return f"Page idle — nothing to wait for (probe: {err})"
    return "Page idle — nothing to wait for"


async def _busy_ui(ctx: Any, on: bool, wait_ms: int) -> None:
    """Page overlay + pool row while the wait runs (best effort, never raises)."""
    pool = getattr(ctx.bridge, "_page_pool", None)
    try:
        if on:
            await ctx.ctrl.show_watcher_overlay(OVERLAY_MESSAGE, kind="generation",
                                                timeout_sec=max(1, wait_ms // 1000))
            if pool:
                pool.mark_waiting(ctx.tab_id, "generation")
        else:
            await ctx.ctrl.hide_watcher_overlay()
            if pool:
                pool.mark_busy(ctx.tab_id, ctx.job_id)
        if pool:
            ctx.bridge._emit_pool_status()
    except Exception:
        pass


async def _wait_idle(ctx: Any, block: Any, limit_ms: int) -> Tuple[str, str]:
    """Poll until idle / timeout / cancel → (status, message)."""
    start = time.monotonic()
    poll = poll_seconds(block)
    while True:
        if _cancelled(ctx):
            return "skipped", "Cancelled while waiting for the page"
        elapsed = int((time.monotonic() - start) * 1000)
        if elapsed >= limit_ms:
            _log(ctx, f"⚠ {_name(block)}: page still busy after {limit_ms} ms — continuing "
                      f"(this block never fails a job)", "warn")
            return "success", f"Still busy after {limit_ms} ms — continuing"
        await asyncio.sleep(poll)
        res = await probe_processing(ctx, block)
        if not res["processing"]:
            return "success", f"Processing finished after {elapsed + int(poll * 1000)} ms"


async def handle_await_processing(ctx: Any, block: Any) -> None:
    """Wait while a processing indicator is visible; an idle page continues at once."""
    limit_ms = timeout_ms(block)
    res = await probe_processing(ctx, block)
    if not res["processing"]:
        _emit(ctx, block, "success", _idle_message(res))
        return
    what = describe(res)
    _emit(ctx, block, "waiting", f"Page busy ({what}) — waiting up to {limit_ms} ms for it to finish")
    _log(ctx, f"⏳ {_name(block)}: {what} — waiting up to {limit_ms} ms", "info")
    await _busy_ui(ctx, True, limit_ms)
    try:
        status, msg = await _wait_idle(ctx, block, limit_ms)
    finally:
        await _busy_ui(ctx, False, 0)
    _emit(ctx, block, status, msg)
