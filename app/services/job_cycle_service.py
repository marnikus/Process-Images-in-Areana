"""Job Cycle & Cooldown Service — post-generation reset + cooldown handling.

RULE 18: file 150-300 LOC ideal, current ~280 LOC.
RULE 16: func ≤30 LOC, CC ≤10, nesting ≤4, params ≤4.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.core.cooldown import (
    apply_captcha_penalty,
    calculate_cooldown_until,
    epoch_to_iso,
    now_epoch,
    parse_iso_to_epoch,
)
from app.core.models import UrlRow

log = logging.getLogger("arena")


def _log_safe(log_cb, msg: str, level: str = "info"):
    if not log_cb:
        return
    try:
        log_cb(msg, level)
    except Exception:
        pass


async def _try_reset_method(controller, timeout_sec: int, log_cb):
    if not hasattr(controller, "reset_to_new_chat"):
        return None
    ok, reason = await controller.reset_to_new_chat(timeout_sec=timeout_sec)
    _log_safe(log_cb, f"New Chat reset {ok} {reason}", "success" if ok else "warn")
    return ok, reason


async def _try_click_method(controller, log_cb):
    if not hasattr(controller, "click_new_chat"):
        return None
    ok, reason = await controller.click_new_chat()
    if not ok:
        return ok, reason
    await asyncio.sleep(2)
    try:
        ready, _ = await controller.is_page_ready()
        if ready:
            return True, "Clicked and ready"
    except Exception:
        pass
    return ok, reason


async def reset_tab_to_new_chat(controller, timeout_sec: int = 15, log_cb=None) -> tuple[bool, str]:
    if not controller:
        return False, "No controller"
    try:
        res = await _try_reset_method(controller, timeout_sec, log_cb)
        if res is not None:
            return res
        res2 = await _try_click_method(controller, log_cb)
        if res2 is not None:
            return res2
    except Exception as e:
        _log_safe(log_cb, f"Reset failed {e}", "error")
        return False, str(e)
    return False, "No reset method"


def set_url_cooldown(url_row: UrlRow, cooldown_seconds: int, last_completed_iso: Optional[str] = None) -> UrlRow:
    now = now_epoch()
    last_epoch = parse_iso_to_epoch(last_completed_iso) if last_completed_iso else now
    until_epoch = calculate_cooldown_until(last_epoch, cooldown_seconds, now=now)
    url_row.cooldown_until = epoch_to_iso(until_epoch)
    url_row.cooldown_seconds = int(cooldown_seconds)
    url_row.last_completed_at = last_completed_iso or epoch_to_iso(now)
    return url_row


def apply_captcha_penalty_to_url(url_row: UrlRow, penalty_seconds: Optional[int] = None) -> UrlRow:
    pen = penalty_seconds if penalty_seconds is not None else url_row.captcha_penalty_seconds
    cur_until = parse_iso_to_epoch(url_row.cooldown_until)
    new_until = apply_captcha_penalty(cur_until, pen, now=now_epoch())
    url_row.cooldown_until = epoch_to_iso(new_until)
    url_row.captcha_count += 1
    url_row.total_cooldown_penalties += 1
    return url_row


def reset_url_cooldown(url_row: UrlRow) -> UrlRow:
    url_row.cooldown_until = None
    url_row.captcha_count = 0
    return url_row


def set_pool_cooldown(pool, tab_id: str, cooldown_seconds: int, last_completed_iso: Optional[str] = None) -> bool:
    try:
        return pool.set_cooldown(tab_id, cooldown_seconds, last_completed_iso)
    except Exception as e:
        log.debug(f"set_pool_cooldown failed {e}")
        return False


def reset_pool_cooldown(pool, tab_id: str) -> bool:
    try:
        return pool.reset_cooldown(tab_id)
    except Exception as e:
        log.debug(f"reset_pool_cooldown failed {e}")
        return False


def apply_pool_captcha_penalty(pool, tab_id: str, penalty_seconds: int) -> bool:
    try:
        return pool.apply_captcha_penalty(tab_id, penalty_seconds)
    except Exception as e:
        log.debug(f"apply_pool_penalty failed {e}")
        return False


def _get_cooldown_seconds(bridge, url_row: Optional[UrlRow]) -> int:
    if url_row:
        try:
            return int(getattr(url_row, "cooldown_seconds", 300) or 300)
        except Exception:
            return 300
    try:
        return int(bridge.state.settings.cooldown.get("min_cooldown_seconds", 300))
    except Exception:
        return 300


def _is_reset_enabled(bridge) -> bool:
    try:
        return bool(bridge.state.settings.cooldown.get("post_generation_reset", True))
    except Exception:
        return True


def _get_reset_timeout(bridge) -> int:
    try:
        return int(bridge.state.settings.cooldown.get("reset_timeout_sec", 15))
    except Exception:
        return 15


def _get_now_iso() -> Optional[str]:
    try:
        from app.core.cooldown import now_iso as cd_now_iso

        return cd_now_iso()
    except Exception:
        return None


def _emit_states(bridge, pool):
    try:
        if hasattr(bridge, "_emit_arena_state"):
            bridge._emit_arena_state()
    except Exception:
        pass
    try:
        if pool and hasattr(bridge, "_emit_pool_status"):
            bridge._emit_pool_status()
    except Exception:
        pass


from dataclasses import dataclass


@dataclass
class JobCycleCtx:
    bridge: object
    pool: object
    tab_id: str
    url_row: Optional[UrlRow]
    controller: object = None


def _get_cooldown_seconds_ctx(ctx: JobCycleCtx) -> int:
    return _get_cooldown_seconds(ctx.bridge, ctx.url_row)


def _get_penalty_seconds_ctx(ctx: JobCycleCtx) -> int:
    return _get_penalty_seconds(ctx.bridge, ctx.url_row)


async def handle_job_completed_cycle(ctx: JobCycleCtx) -> dict:
    return await _handle_completed_ctx(ctx)


async def _handle_completed_ctx(ctx: JobCycleCtx) -> dict:
    result = {"reset_ok": False, "cooldown_set": False, "until": None}
    try:
        cd_sec = _get_cooldown_seconds_ctx(ctx)
        if _is_reset_enabled(ctx.bridge) and ctx.controller:
            timeout = _get_reset_timeout(ctx.bridge)
            cb = ctx.bridge._log if hasattr(ctx.bridge, "_log") else None
            ok, reason = await reset_tab_to_new_chat(ctx.controller, timeout_sec=timeout, log_cb=cb)
            result["reset_ok"] = ok
            result["reset_reason"] = reason
        now_iso_str = _get_now_iso()
        if ctx.url_row:
            set_url_cooldown(ctx.url_row, cd_sec, last_completed_iso=now_iso_str)
            result["until"] = ctx.url_row.cooldown_until
        if ctx.pool and ctx.tab_id:
            set_pool_cooldown(ctx.pool, ctx.tab_id, cd_sec, last_completed_iso=now_iso_str)
            result["cooldown_set"] = True
        _emit_states(ctx.bridge, ctx.pool)
    except Exception as e:
        log.warning(f"handle_job_completed_cycle failed {e}")
        result["error"] = str(e)
    return result


def _get_penalty_seconds(bridge, url_row: Optional[UrlRow]) -> int:
    if url_row:
        try:
            return int(getattr(url_row, "captcha_penalty_seconds", 900) or 900)
        except Exception:
            return 900
    try:
        return int(bridge.state.settings.cooldown.get("captcha_penalty_seconds", 900))
    except Exception:
        return 900


async def handle_captcha_detected_cycle(ctx: JobCycleCtx) -> dict:
    return await _handle_captcha_ctx(ctx)


async def _handle_captcha_ctx(ctx: JobCycleCtx) -> dict:
    result = {"penalty_applied": False, "new_until": None}
    try:
        pen_sec = _get_penalty_seconds_ctx(ctx)
        if ctx.url_row:
            apply_captcha_penalty_to_url(ctx.url_row, penalty_seconds=pen_sec)
            result["new_until"] = ctx.url_row.cooldown_until
        if ctx.pool and ctx.tab_id:
            apply_pool_captcha_penalty(ctx.pool, ctx.tab_id, pen_sec)
            result["penalty_applied"] = True
        _emit_states(ctx.bridge, ctx.pool)
    except Exception as e:
        log.warning(f"handle_captcha failed {e}")
        result["error"] = str(e)
    return result
