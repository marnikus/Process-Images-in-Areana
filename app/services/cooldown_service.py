# ideal-size: ~720 lines reason=single cohesive job-cycle service; sync pool ops and async finish/wait share FinishCtx and helpers, splitting would make two files that always change together (RULE 18.2)
"""Job-cycle cooldowns — per-tab pause, reset, captcha penalty (spec 01-04).

Sync pool ops run under the pool lock; async cycle (`finish_page_after_job`,
`wait_for_tab_ready`) wires reset + pause into both dispatch paths. PagePool
is at its 15-method limit, so ops live here as functions. Imports go
services -> browser/core only.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from app.browser.new_chat import ResetCtx, reset_to_new_chat
from app.browser.page_status import PageInfo, PageStatus, now_iso
from app.core.cooldown import (
    DEFAULT_MIN_SECONDS,
    DEFAULT_PENALTY_SECONDS,
    DEFAULT_RATE_LIMIT_PENALTY_SECONDS,
    CooldownConfig,
    clamp_seconds,
    cooldown_total,
    format_remaining,
)

_POLL_SEC = 2.0
_LOG_EVERY_SEC = 10.0
_STUCK_STATUSES = frozenset({PageStatus.BUSY, PageStatus.WAITING_GENERATION,
                              PageStatus.WAITING_CAPTCHA, PageStatus.ERROR})


@dataclass
class FinishCtx:
    """Post-job context to keep params small (RULE 16)."""

    pool: Any
    bridge: Any
    tab_id: str
    ctrl: Any
    client: Any
    pending_before: int = 0
    captcha_before: int = 0
    rate_limit_before: int = 0


def _safe_int(get_state, key: str, default: int) -> int:
    """Read clamped seconds, forgiving bad stored values."""
    try:
        raw = get_state(key, default)
    except Exception:
        return default
    return clamp_seconds(raw, default)


def load_config(get_state) -> CooldownConfig:
    """Read user settings via session getter (bridge.config.get_state)."""
    try:
        enabled = bool(get_state("cooldown_enabled", True))
    except Exception:
        enabled = True
    base = _safe_int(get_state, "cooldown_min_seconds", DEFAULT_MIN_SECONDS)
    penalty = _safe_int(get_state, "cooldown_captcha_penalty_seconds", DEFAULT_PENALTY_SECONDS)
    rate_limit = _safe_int(get_state, "cooldown_rate_limit_penalty_seconds",
                           DEFAULT_RATE_LIMIT_PENALTY_SECONDS)
    return CooldownConfig(enabled=enabled, min_seconds=base, captcha_penalty_seconds=penalty,
                          rate_limit_penalty_seconds=rate_limit)


def _settle_steady(page) -> bool:
    """Mark ready when no pause is needed."""
    page.status = PageStatus.STEADY
    page.current_job_id = None
    page.cooldown_until = 0.0
    page.cooldown_total = 0
    page.cooldown_reason = ""
    page.last_steady_at = now_iso()
    page.error = None
    return True


def _fill_missing(page, title: str, url: str) -> None:
    """Fill empty display fields; never clobbers filled ones."""
    try:
        if not page.url and url:
            page.url = url
        if not page.title and title:
            page.title = title
    except Exception:
        pass


def ensure_pool_page(pool: Any, info: PageInfo) -> bool:
    """Register-if-missing so single-tab batches always have a page to cool."""
    if pool is None or not info.tab_id:
        return False
    try:
        page = pool.get_page(info.tab_id)
    except Exception:
        return False
    if page is None:
        try:
            pool.add_page(info)
            return True
        except Exception:
            return False
    with pool._lock:
        _fill_missing(page, info.title, info.url)
    return True


def _abort_set(pool: Any) -> set:
    """Per-tab abort flags, created on first use."""
    aborts = getattr(pool, "_aborts", None)
    if aborts is None:
        aborts = pool._aborts = set()
    return aborts


def request_tab_abort(pool: Any, tab_id: str) -> bool:
    """Flag the tab's live job to stop; False when no job there."""
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is None or not getattr(page, "current_image", None):
                return False
            _abort_set(pool).add(tab_id)
            return True
    except Exception:
        return False


def is_tab_aborted(pool: Any, tab_id: str) -> bool:
    """Operator stop requested for this tab's job."""
    try:
        return tab_id in getattr(pool, "_aborts", ())
    except Exception:
        return False


def clear_tab_abort(pool: Any, tab_id: str) -> None:
    """Drop a consumed/stale stop request."""
    try:
        with pool._lock:
            getattr(pool, "_aborts", set()).discard(tab_id)
    except Exception:
        pass


def set_tab_image(pool: Any, tab_id: str, name) -> None:
    """Record/clear the image this tab is processing."""
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is not None:
                page.current_image = name or None
    except Exception:
        pass


def tab_has_live_job(pool: Any, tab_id: str) -> bool:
    """A job is active on this tab (either run path sets the image).

    Stale BUSY without an image is a leftover, not a live job, so it
    must never block an operator reset.
    """
    try:
        page = pool.get_page(tab_id) if pool else None
        if page is None:
            return False
        return bool(getattr(page, "current_image", None))
    except Exception:
        return False


def _snapshot_free(pages, tab_id: str) -> bool:
    """Preferred tab is pooled and free right now."""
    for p in pages or []:
        if p.get("tab_id") == tab_id:
            return p.get("status") == "steady" and bool(p.get("is_connected", False))
    return False


def _best_ready_id(pages) -> str:
    """Free tab with fewest jobs; ties keep pool order, else ''."""
    free = [p for p in pages or []
            if p.get("status") == "steady" and p.get("is_connected", False)]
    if not free:
        return ""
    best = min(free, key=lambda p: p.get("jobs_completed", 0) or 0)
    return best.get("tab_id", "") or ""


def _first_connected_id(pages) -> str:
    """First pooled tab id worth waiting on (e.g. while it cools)."""
    for p in pages or []:
        if p.get("tab_id", "") and p.get("is_connected", False):
            return p.get("tab_id", "")
    return ""


def _resolve_allowed_tab(pages, tab_id: str, allowed: set) -> str:
    """Candidates restricted to checked tabs; '' = nothing usable (I-33)."""
    pages = [p for p in pages if p.get("tab_id", "") in allowed]
    if tab_id not in allowed:
        tab_id = ""
    if tab_id and _snapshot_free(pages, tab_id):
        return tab_id
    if tab_id:
        return _best_ready_id(pages) or tab_id  # cooling: caller waits
    return _best_ready_id(pages) or _first_connected_id(pages)


def resolve_primary_tab(pool: Any, tab_id: str, allowed=None) -> str:
    """Keep a free preferred tab; a stale/busy one heals to best ready.

    `allowed` (checked-row tab ids, I-33) restricts every candidate; a
    foreign preferred tab moves, and '' means nothing checked is usable."""
    tab_id = tab_id or ""
    if pool is None:
        return tab_id
    try:
        pages = pool.status_snapshot().get("pages", [])
    except Exception:
        return tab_id
    if allowed is not None:
        return _resolve_allowed_tab(pages, tab_id, allowed)
    if not tab_id:
        if len(pages) == 1:
            return pages[0].get("tab_id", "")
        return ""
    if _snapshot_free(pages, tab_id):
        return tab_id
    return _best_ready_id(pages) or tab_id


def _restore_pending(page, entry: dict) -> None:
    """Restore stacked penalty/captcha highs (never lowers live values)."""
    pending = int(entry.get("pending_penalty", 0) or 0)
    if pending > 0:
        page.pending_penalty = max(page.pending_penalty, pending)
    captcha = int(entry.get("captcha_count", 0) or 0)
    if captcha > 0:
        page.captcha_count = max(page.captcha_count, captcha)


def _now_or(now: float | None) -> float:
    """Injectable clock for deterministic restore tests."""
    return time.time() if now is None else now


def _restore_cooldown_allowed(page, until: float, moment: float) -> bool:
    """Live cooldown applies only when it extends (never shortens)."""
    if until <= moment:
        return False
    return until > (page.cooldown_until or 0)


def _apply_restored_cooldown(page, entry: dict, until: float) -> None:
    """Set wall-clock pause fields (call with pool lock held)."""
    page.status = PageStatus.COOLDOWN
    page.cooldown_until = until
    page.cooldown_total = int(entry.get("cooldown_total", 0) or 0)
    page.cooldown_reason = entry.get("reason", "") or "restored"
    page.current_job_id = None


def _restore_worthwhile(until: float, pending: int, moment: float) -> bool:
    """Persisted entry matters only with future time or stacked penalty."""
    return until > moment or pending > 0


def _steady_page(pool: Any, tab_id: str):
    """Registered page when steady, else None (restore targets steady only)."""
    try:
        page = pool.get_page(tab_id)
    except Exception:
        return None
    if page is None or page.status != PageStatus.STEADY:
        return None
    return page


def restore_cooldown_entry(pool: Any, tab_id: str, entry: dict, now: float | None = None) -> bool:
    """Re-apply persisted wall-clock pause; never shortens a live timer."""
    if not entry or not tab_id:
        return False
    page = _steady_page(pool, tab_id)
    if page is None:
        return False
    try:
        moment = _now_or(now)
        until = float(entry.get("cooldown_until", 0) or 0)
        pending = int(entry.get("pending_penalty", 0) or 0)
        if not _restore_worthwhile(until, pending, moment):
            return False
        with pool._lock:
            if _restore_cooldown_allowed(page, until, moment):
                _apply_restored_cooldown(page, entry, until)
            _restore_pending(page, entry)
        return True
    except Exception:
        return False


def start_cooldown(pool, tab_id, base_seconds, reason="") -> bool:
    """Start the per-tab pause; applies stacked captcha penalty."""
    with pool._lock:
        page = pool._pages.get(tab_id)
        if page is None:
            return False
        total = cooldown_total(int(base_seconds or 0), page.pending_penalty)
        page.pending_penalty = 0
        page.last_job_at = now_iso()
        if total <= 0:
            return _settle_steady(page)
        page.status = PageStatus.COOLDOWN
        page.cooldown_until = time.time() + total
        page.cooldown_total = total
        page.cooldown_reason = reason or "job done"
        page.current_job_id = None
        return True


def add_captcha_penalty(pool, tab_id, penalty_seconds) -> int:
    """Stack +penalty on this tab only; returns count (-1 unknown)."""
    extra = clamp_seconds(penalty_seconds, 0)
    with pool._lock:
        page = pool._pages.get(tab_id)
        if page is None:
            return -1
        page.captcha_count += 1
        if page.status == PageStatus.COOLDOWN and page.is_cooling():
            page.cooldown_until += extra
            page.cooldown_total += extra
        else:
            page.pending_penalty += extra
        return page.captcha_count


def _penalty_from(bridge) -> int:
    """Read the per-captcha seconds; default 900, never below 0."""
    try:
        get_state = getattr(getattr(bridge, "config", None), "get_state", None)
        if get_state:
            return max(0, int(get_state("cooldown_captcha_penalty_seconds", 900)))
    except Exception:
        pass
    return 900


def _persist_emit(bridge) -> None:
    """Save timers + refresh rows; best effort, never raises."""
    for name in ("_persist_cooldowns", "_emit_pool_status"):
        try:
            fn = getattr(bridge, name, None)
            if fn:
                fn()
        except Exception:
            pass


def _cooldown_suffix(page, penalty) -> str:
    """Log tail: live extension or stacked pending (shared by captcha + rate-limit)."""
    if page is not None and page.status == PageStatus.COOLDOWN and page.is_cooling():
        return f"live cooldown extended to {format_remaining(page.cooldown_total)}"
    pending = page.pending_penalty if page else 0
    return f"pending {format_remaining(pending)} stacks onto next cooldown"


def note_captcha_event(pool, tab_id, bridge, source="job") -> int:
    """Record one solved captcha: stack, log, persist, emit. -1 unknown."""
    if pool is None or not tab_id:
        _log(bridge, f"Captcha NOT recorded (no pool/tab) via {source}", "warn")
        return -1
    penalty = _penalty_from(bridge)
    count = add_captcha_penalty(pool, tab_id, penalty)
    if count < 0:
        _log(bridge, f"Captcha NOT recorded on tab {str(tab_id)[:12]} (unknown tab) via {source} — no extra cooldown", "warn")
        return -1
    try:
        page = pool.get_page(tab_id)
    except Exception:
        page = None
    _log(bridge, f"\U0001f6e1\ufe0f Captcha +{penalty // 60}m tab {str(tab_id)[:12]} (x{count}) via {source} — {_cooldown_suffix(page, penalty)}", "warn")
    _persist_emit(bridge)
    return count


def _rate_limit_penalty_from(bridge) -> int:
    """Read the per-rate-limit seconds; default 1800, never below 0."""
    try:
        get_state = getattr(getattr(bridge, "config", None), "get_state", None)
        if get_state:
            return max(0, int(get_state("cooldown_rate_limit_penalty_seconds",
                                        DEFAULT_RATE_LIMIT_PENALTY_SECONDS)))
    except Exception:
        pass
    return DEFAULT_RATE_LIMIT_PENALTY_SECONDS


def add_rate_limit_penalty(pool, tab_id, penalty_seconds) -> int:
    """Stack +penalty on this tab only; returns count (-1 unknown)."""
    extra = clamp_seconds(penalty_seconds, 0)
    with pool._lock:
        page = pool._pages.get(tab_id)
        if page is None:
            return -1
        page.rate_limit_count += 1
        if page.status == PageStatus.COOLDOWN and page.is_cooling():
            page.cooldown_until += extra
            page.cooldown_total += extra
        else:
            page.pending_penalty += extra
        return page.rate_limit_count


def note_rate_limit_event(pool, tab_id, bridge) -> int:
    """Stack the configured rate-limit penalty; 0 when disabled, -1 unknown tab."""
    penalty = _rate_limit_penalty_from(bridge)
    if penalty <= 0 or pool is None or not tab_id:
        return 0
    count = add_rate_limit_penalty(pool, tab_id, penalty)
    if count < 0:
        _log(bridge, f"⚠ Rate-limit penalty skipped on tab {str(tab_id)[:12]} (unknown tab)", "warn")
        return -1
    try:
        page = pool.get_page(tab_id)
    except Exception:
        page = None
    _log(bridge, f"⛔ Rate limit +{penalty // 60}m tab {str(tab_id)[:12]} (x{count}) — {_cooldown_suffix(page, penalty)}", "warn")
    _persist_emit(bridge)
    return count


def maybe_note_rate_limit(pool, tab_id, bridge, error) -> int:
    """Apply the rate-limit penalty when the job error is a rate/limit signal."""
    from app.utils.page_errors import is_rate_limit_error
    if not is_rate_limit_error(error):
        return 0
    return note_rate_limit_event(pool, tab_id, bridge)


async def wait_captcha_cleared(ctrl, stop, timeout_sec, log) -> bool:
    """Poll until the dialog clears; False only on stop (never gives up)."""
    start = time.monotonic()
    warned = 0.0
    while True:
        try:
            visible = await ctrl.is_security_dialog_visible()
        except Exception:
            return True
        if not visible:
            return True
        if stop():
            return False
        now = time.monotonic()
        if now - start > timeout_sec and now - warned >= 5:
            warned = now
            log(f"\u23f0 Captcha wait {int(now - start)}s/{timeout_sec}s — still waiting", "error")
        await asyncio.sleep(_POLL_SEC)


def reset_cooldown(pool, tab_id) -> bool:
    """User reset: ready now; keeps the job-cycle captcha debt."""
    with pool._lock:
        page = pool._pages.get(tab_id)
        if page is None:
            return False
        if page.status != PageStatus.COOLDOWN:
            return True
        return _settle_steady(page)


def is_stuck_status(status) -> bool:
    """Busy-like states a finished run can leave behind (never a timer)."""
    try:
        return status in _STUCK_STATUSES
    except Exception:
        return False


def force_reset_page(pool: Any, tab_id: str) -> bool:
    """Operator reset: free a stuck page; history (jobs/captchas) kept."""
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is None:
                return False
            page.status = PageStatus.STEADY
            page.current_job_id = None
            page.busy_since = None
            page.cooldown_until = 0.0
            page.cooldown_total = 0
            page.cooldown_reason = ""
            page.pending_penalty = 0
            page.error = None
            page.last_steady_at = now_iso()
            return True
    except AttributeError:
        return False


def edit_cooldown(pool, tab_id, seconds) -> bool:
    """User edit: set remaining pause (0 = ready now)."""
    total = clamp_seconds(seconds, 0)
    with pool._lock:
        page = pool._pages.get(tab_id)
        if page is None or page.is_busy():
            return False
        if total <= 0:
            return _settle_steady(page)
        page.status = PageStatus.COOLDOWN
        page.cooldown_until = time.time() + total
        page.cooldown_total = total
        page.cooldown_reason = "manual"
        return True


def refresh_expired(pool, now=None) -> list:
    """Flip expired timers to STEADY; returns freed tab ids."""
    freed = []
    with pool._lock:
        for tab_id, page in pool._pages.items():
            try:
                if page.try_expire(now):
                    freed.append(tab_id)
            except Exception:
                continue
    return freed


def longest_remaining(pool, now=None) -> int:
    """Max live countdown across tabs (0 when none cooling)."""
    best = 0
    with pool._lock:
        for page in pool._pages.values():
            try:
                left = page.remaining_seconds(now)
            except Exception:
                continue
            if left > best:
                best = left
    return best


def cooldown_aware_timeout(pool, default_sec=600.0, extra_sec=60.0) -> float:
    """Free-page wait must outlive the longest per-tab pause."""
    try:
        longest = longest_remaining(pool)
    except Exception:
        return float(default_sec)
    return max(float(default_sec), float(longest + extra_sec))


def remaining_for(pool, tab_id, now=None) -> int:
    """Live countdown for one tab (-1 when unknown)."""
    page = pool.get_page(tab_id)
    if page is None:
        return -1
    try:
        return page.remaining_seconds(now)
    except Exception:
        return 0


def _is_cancelled(bridge) -> bool:
    return bool(getattr(bridge, "_cancel_requested", False))


def _is_paused(bridge) -> bool:
    return bool(getattr(bridge, "_pause_requested", False))


def _log(bridge, message: str, level: str = "info"):
    try:
        bridge._log(message, level)
    except Exception:
        pass


async def _honour_pause(bridge):
    """Wait while paused; cancel still breaks (RULE 7)."""
    while _is_paused(bridge):
        if _is_cancelled(bridge):
            break
        await asyncio.sleep(1.0)


async def wait_for_tab_ready(pool, tab_id, bridge) -> bool:
    """Single-page gate: wait until this tab's pause expires."""
    last_log = 0.0
    while True:
        if _is_cancelled(bridge):
            return False
        await _honour_pause(bridge)
        if _is_cancelled(bridge):
            return False
        refresh_expired(pool)
        page = pool.get_page(tab_id)
        if page is None:
            _log(bridge, f"Tab {str(tab_id)[:8]} unknown to pool — proceeding", "warn")
            return True
        if page.is_free() or page.remaining_seconds() <= 0:
            return True
        now_m = time.monotonic()
        if now_m - last_log >= _LOG_EVERY_SEC:
            last_log = now_m
            left = format_remaining(page.remaining_seconds())
            _log(bridge, f"⏳ Tab {str(tab_id)[:8]} cooling {left} — next job waits", "info")
        await asyncio.sleep(_POLL_SEC)


def _is_cooling_now(pool, tab_id: str) -> bool:
    """True when the tab currently gates jobs behind its pause."""
    try:
        page = pool.get_page(tab_id)
        return page is not None and page.is_cooling()
    except Exception:
        return False


async def wait_for_batch_ready(pool, tab_ids, bridge) -> bool:
    """Batch-start gate: every listed tab steady before the first job."""
    for tab_id in tab_ids or []:
        if not tab_id:
            continue
        if _is_cooling_now(pool, tab_id):
            _log(bridge, f"⏳ New Start during cooldown — tab {str(tab_id)[:8]} must reach 00:00 + ready first", "info")
        if not await wait_for_tab_ready(pool, tab_id, bridge):
            return False
    return True


async def finish_page_after_job(ctx: FinishCtx) -> bool:
    """Post-job cycle: reset page, then pause or ready (spec 01+02)."""
    if _is_cancelled(ctx.bridge):
        return await _finish_cancelled(ctx)
    return await _finish_normal(ctx)


def _settle_pool_steady(ctx: FinishCtx) -> bool:
    try:
        return bool(ctx.pool.mark_steady(ctx.tab_id))
    except Exception:
        return False


def _emit_status(ctx: FinishCtx):
    try:
        ctx.bridge._emit_pool_status()
    except Exception:
        pass


async def _best_effort_reset(ctx: FinishCtx, timeout_sec: float) -> tuple[bool, str]:
    """Reset that never raises — failure is logged, never fatal."""
    try:
        reset_ctx = ResetCtx(ctrl=ctx.ctrl, client=ctx.client, engine=ctx.bridge,
                             timeout_sec=timeout_sec,
                             cancel_check=lambda: _is_cancelled(ctx.bridge))
        return await reset_to_new_chat(reset_ctx)
    except Exception as e:
        return False, str(e)


def register_job_done(pool: Any, tab_id: str) -> int:
    """Count one finished job for load balancing; -1 when unknown."""
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is None:
                return -1
            page.jobs_completed += 1
            page.last_job_at = now_iso()
            return page.jobs_completed
    except AttributeError:
        return -1


def _stats_count(stats: dict, norm_key: str) -> int:
    """Saved counter for a normalized URL key; 0 when absent."""
    if not isinstance(stats, dict) or not norm_key:
        return 0
    val = stats.get(norm_key, {})
    if not isinstance(val, dict):
        return 0
    count = val.get("jobs_completed", 0)
    if isinstance(count, bool) or not isinstance(count, int):
        return 0
    return max(count, 0)


def restore_page_stats(pool: Any, tab_id: str, norm_url: str, stats: dict) -> int:
    """Re-apply one tab's saved counter; live never moves backwards."""
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is None:
                return -1
            page.jobs_completed = max(page.jobs_completed, _stats_count(stats, norm_url))
            return page.jobs_completed
    except AttributeError:
        return -1


async def _finish_cancelled(ctx: FinishCtx) -> bool:
    """Cancel path: hygiene reset, ready at once, no pause."""
    await _best_effort_reset(ctx, timeout_sec=15.0)
    ok = _settle_pool_steady(ctx)
    _emit_status(ctx)
    _log(ctx.bridge, f"✅ Page {str(ctx.tab_id)[:12]} STEADY ready (no cooldown after cancel)",
         "success")
    return ok


def _reason_for(ctx: FinishCtx) -> str:
    """Cooldown reason incl. stacked captcha count for the UI."""
    try:
        page = ctx.pool.get_page(ctx.tab_id)
        pending = page.pending_penalty if page else 0
        count = page.captcha_count if page else 0
    except Exception:
        return "job done"
    if pending > 0 and count > 0:
        return f"job done +captcha x{count}"
    return "job done"


def _capture_pending(ctx) -> None:
    """Snapshot stacked debt before start consumes it (for the log)."""
    try:
        page = ctx.pool.get_page(ctx.tab_id)
        ctx.pending_before = page.pending_penalty if page else 0
        ctx.captcha_before = page.captcha_count if page else 0
        ctx.rate_limit_before = page.rate_limit_count if page else 0
    except Exception:
        pass


def _finish_detail(ctx) -> str:
    """Breakdown: ' (total 20:00 = base 05:00 + captcha 15:00 x1)'; '' when plain."""
    try:
        if ctx.pending_before <= 0:
            return ""
        page = ctx.pool.get_page(ctx.tab_id)
        total = page.cooldown_total if page else 0
        base = max(0, total - ctx.pending_before)
        if ctx.rate_limit_before > 0:
            return (f" (total {format_remaining(total)} = base {format_remaining(base)}"
                    f" + extra {format_remaining(ctx.pending_before)}"
                    f" (captcha x{ctx.captcha_before}, rate-limit x{ctx.rate_limit_before}))")
        return (f" (total {format_remaining(total)} = base {format_remaining(base)}"
                f" + captcha {format_remaining(ctx.pending_before)} x{ctx.captcha_before})")
    except Exception:
        return ""


def _log_finish(ctx: FinishCtx, started: bool):
    """Report the new countdown (RULE 2)."""
    if not started:
        _log(ctx.bridge, f"⚠ Page {str(ctx.tab_id)[:12]} cooldown not started (unknown tab)", "warn")
        return
    left = remaining_for(ctx.pool, ctx.tab_id)
    _log(ctx.bridge, f"⏳ Page {str(ctx.tab_id)[:12]} cooling {format_remaining(left)}{_finish_detail(ctx)} — next job after pause",
         "info")


async def _finish_normal(ctx: FinishCtx) -> bool:
    """Normal path: reset page, then start the per-tab pause."""
    register_job_done(ctx.pool, ctx.tab_id)
    ok, reason = await _best_effort_reset(ctx, timeout_sec=30.0)
    if not ok:
        _log(ctx.bridge, f"⚠ New-chat reset failed ({reason}) — cooling anyway", "warn")
    cfg = load_config(ctx.bridge.config.get_state)
    if not cfg.enabled or cfg.min_seconds <= 0:
        done = _settle_pool_steady(ctx)
        _emit_status(ctx)
        _log(ctx.bridge, f"✅ Page {str(ctx.tab_id)[:12]} STEADY ready (cooldown off)", "success")
        return done
    _capture_pending(ctx)
    started = start_cooldown(ctx.pool, ctx.tab_id, cfg.min_seconds, _reason_for(ctx))
    _emit_status(ctx)
    _log_finish(ctx, started)
    return started
