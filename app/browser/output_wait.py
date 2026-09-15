"""Output wait — polling loop for new-output detection (async).

Owns: wait polling with cancel, spinner awareness, fallback to
newest-large-stable after spinner gone. Uses output_probes for JS and
output_state for pure decisions. Browser layer only.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable

from app.browser.output_probes import build_check_js, build_scroll_bottom_js
from app.browser.output_state import (
    describe_order,
    is_terminal_ready,
    normalize_old_keys,
    select_best_fallback,
    should_accept_fallback,
)


@dataclass
class WaitRequest:
    """Inputs for one wait cycle (parameter object, RULE 19)."""

    baseline: dict
    timeout_ms: int = 180000
    correlation_id: str | None = None
    cancel_check: Callable[[], bool] | None = None
    poll_sec: int = 2


@dataclass
class _WaitState:
    """Mutable polling progress (seen, logs, stability)."""

    start: float
    keys: frozenset
    seen: bool = False
    last_log: float = 0.0
    last_scroll: float = 0.0
    stable_src: str | None = None
    stable_count: int = 0


def _is_cancelled(req: WaitRequest) -> bool:
    """True when caller requested cancel (RULE 7)."""
    try:
        return bool(req.cancel_check and req.cancel_check())
    except Exception:
        return False


async def _poll_once(cdp: Any, keys: set, corr: str | None) -> dict | None:
    """Evaluate check JS once, return dict or None."""
    js = build_check_js(list(keys), corr)
    try:
        result = await cdp.evaluate(js)
    except Exception:
        return None
    return result if isinstance(result, dict) else None


def _note_spinning(log_fn: Any, result: dict, seen: bool, last: float):
    """Log spinner start and periodic still-generating."""
    now = time.time()
    if not seen:
        log_fn(f"⏳ Generation started — spinner visible {result.get('spinDetails')}", "info")
        return True, now
    if now - last > 10:
        log_fn(f"⏳ Still generating... spinner {result.get('spinCount')} reason={result.get('reason')}", "info")
        return seen, now
    return seen, last


def _best_candidate(result: dict) -> dict | None:
    """Best fallback: below-pool first, never a reference."""
    details = result.get("fallbackDetails")
    if not details:
        raw = result.get("allNewDetails") or []
        details = [d for d in raw if not d.get("isReference")]
    if not details:
        return None
    return select_best_fallback(details)


def _update_stable(prev: str | None, count: int, cur: str | None):
    """Track same-src stability across polls."""
    if cur and cur == prev:
        return prev, count + 1
    if cur:
        return cur, 1
    return None, 0


def _wants_fallback(result: dict, stable: int, elapsed: float) -> bool:
    """True when spinner gone plus stable large candidate."""
    spinning = bool(result.get("spinning"))
    return should_accept_fallback(spinning, stable, elapsed)


def _log_waiting(log_fn: Any, result: dict, last: float) -> float:
    """Periodic waiting log with order diagnostics."""
    now = time.time()
    if now - last <= 10:
        return last
    log_fn(f"⏳ Waiting... {describe_order(result)}", "info")
    debug = result.get("debugAllImgs")
    if debug:
        log_fn(f"🔍 debugAllImgs sample: {debug[:3]}", "info")
    return now


async def _maybe_scroll(cdp: Any, elapsed: float, last: float) -> float:
    """Scroll container every 30s to trigger lazy load."""
    if elapsed - last < 30:
        return last
    try:
        await cdp.evaluate(build_scroll_bottom_js())
    except Exception:
        pass
    return elapsed


def _decide_done(log_fn: Any, result: dict, state: _WaitState):
    """Check ready or stable fallback, update stability."""
    if is_terminal_ready(result):
        src = result.get("src", "")
        log_fn(f"✅ New output ready: {src[:80]}", "success")
        done = ("completed", {"new_src": src, "check": result})
        return True, done
    best = _best_candidate(result)
    best_src = best.get("src") if best else None
    updated = _update_stable(state.stable_src, state.stable_count, best_src)
    state.stable_src, state.stable_count = updated
    elapsed = time.time() - state.start
    if best_src and _wants_fallback(result, state.stable_count, elapsed):
        log_fn(f"⚠ Fallback newest-large {state.stable_count}x: {best_src[:80]}", "warn")
        payload = {"new_src": best_src, "check": result, "fallback": True}
        payload["rect"] = best.get("rect") if best else None
        return True, ("completed", payload)
    return False, (None, None)


async def wait_for_new(cdp: Any, log_fn: Any, req: WaitRequest) -> tuple:
    """Poll until ready, fallback, cancel, or timeout."""
    keys = normalize_old_keys(req.baseline.get("output_srcs"))
    state = _WaitState(start=time.time(), keys=frozenset(keys))
    last_result: dict | None = None
    while (time.time() - state.start) * 1000 < req.timeout_ms:
        if _is_cancelled(req):
            log_fn("❌ Cancelled during wait", "warn")
            return "failed", {"error": "Cancelled", "cancelled": True}
        result = await _poll_once(cdp, state.keys, req.correlation_id)
        if not result:
            await asyncio.sleep(req.poll_sec)
            continue
        last_result = result
        if result.get("spinning"):
            seen = _note_spinning(log_fn, result, state.seen, state.last_log)
            state.seen, state.last_log = seen
            await asyncio.sleep(req.poll_sec)
            continue
        done, payload = _decide_done(log_fn, result, state)
        if done:
            return payload
        state.last_log = _log_waiting(log_fn, result, state.last_log)
        elapsed = time.time() - state.start
        state.last_scroll = await _maybe_scroll(cdp, elapsed, state.last_scroll)
        await asyncio.sleep(req.poll_sec)
    return "failed", {"error": f"Timeout after {req.timeout_ms}ms", "last_check": last_result}
