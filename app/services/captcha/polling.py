"""Provider polling for CaptchaSolver — 2Captcha get_result loop.

Split from solver.py by responsibility (RULE 18.2): this file owns
"wait for the provider", solver.py owns "apply the token to the page".
Mid-solve page errors are checked EVERY poll round (see provider_result),
so a page that dies during the wait is caught within one interval —
no concurrent watcher is needed for that (design correction 2026-09-18).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional, Tuple

from app.utils.page_errors import match_page_error

from .api_client import ApiError, POLL_INTERVAL_SEC
from .plan import SolvePlan
from .signals import host_of

HEARTBEAT_SEC = 30.0  # processing polls: log a still-waiting line this often
MAX_TRANSIENT_POLL_ERRORS = 3  # tolerate short 2Captcha/HTTP response glitches


def failed_detail(res: Dict[str, Any]) -> str:
    """Provider's own words for a failed task (errorCode preferred)."""
    return str(res.get("errorCode") or res.get("errorDescription") or "")


async def note_page_error(plan: SolvePlan, log) -> bool:
    """Observe a new fatal page error; true means the solve is terminal."""
    if plan.page_error:
        return True
    scan = getattr(plan.ctrl, "scan_page_errors", None)
    if scan is None:
        return False
    try:
        corpus = await scan()
    except Exception:
        return False
    if plan.err_base is None:  # first call: baseline, never report
        plan.err_base = corpus if isinstance(corpus, str) else ""
        return False
    err = match_page_error(corpus if isinstance(corpus, str) else "", plan.err_base)
    if not err:
        return False
    plan.err_seen = True
    plan.page_error_at = time.monotonic() - plan.start
    plan.page_error = err
    log(f"🛡️ page error appeared during solve ({plan.page_error_at:.0f}s in): {err}", "warn")
    return True


def _heartbeat(log, plan: SolvePlan, task_id: str, last: float) -> float:
    """Still-processing line every HEARTBEAT_SEC; returns the new mark."""
    now = time.monotonic()
    if now - last < HEARTBEAT_SEC:
        return last
    log(f"🤖 2Captcha task #{task_id} still processing ({now - plan.start:.0f}s elapsed)", "info")
    return now


def _poll_fail(plan: SolvePlan, why: str, detail: str = "") -> Tuple[None, str]:
    plan.stats.record("auto_failed", host_of(plan.signal.page_url))
    plan.stats.set_last_error(detail or why)
    suffix = f" ({detail})" if detail and detail != why else ""
    plan.logger(f"2Captcha poll ended: {why}{suffix}", "warn")
    return None, why


async def _retry_network(plan: SolvePlan, started: float, count: int,
                         timeout_sec: int) -> bool:
    """Wait before another transient poll; false means retry budget expired."""
    elapsed = time.monotonic() - started
    if count >= MAX_TRANSIENT_POLL_ERRORS or elapsed > timeout_sec:
        return False
    plan.logger(
        f"2Captcha poll network glitch — retrying "
        f"({count}/{MAX_TRANSIENT_POLL_ERRORS}, {elapsed:.0f}s elapsed)", "warn")
    await asyncio.sleep(POLL_INTERVAL_SEC)
    return True


async def provider_result(plan: SolvePlan, res: dict) -> Tuple[bool, Optional[str], str]:
    """Interpret one successful provider response."""
    if await note_page_error(plan, plan.logger):
        return True, None, "page_error"
    status = res.get("status")
    if status == "ready":
        token = str((res.get("solution") or {}).get("gRecaptchaResponse") or "")
        return True, token, ""
    if status == "failed":
        token, why = _poll_fail(plan, "task_failed", failed_detail(res))
        return True, token, why
    return False, None, ""


async def poll_task(plan: SolvePlan, task_id: str,
                    timeout_sec: int) -> Tuple[Optional[str], str]:
    """Poll until a token arrives; (None, why) on stop/error/timeout."""
    start = time.monotonic()
    last_beat = start
    transient_errors = 0
    while True:
        if plan.stop():
            plan.logger("2Captcha polling stopped (user stop)", "info")
            return None, "stopped"
        plan.polls += 1
        try:
            res = await plan.client.get_result(task_id)
        except ApiError as exc:
            transient_errors += 1
            if exc.reason == "network" and await _retry_network(
                    plan, start, transient_errors, timeout_sec):
                continue
            return _poll_fail(plan, exc.reason, str(exc))
        transient_errors = 0
        done, token, why = await provider_result(plan, res)
        if done:
            return token, why
        if time.monotonic() - start > timeout_sec:
            return _poll_fail(plan, "poll_timeout")
        last_beat = _heartbeat(plan.logger, plan, task_id, last_beat)
        await asyncio.sleep(POLL_INTERVAL_SEC)
