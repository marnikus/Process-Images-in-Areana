"""Cooldown-only reset policy shared by URL-row and batch controls.

This service changes page timer/debt fields only. The row's existing stale-job
repair remains a separate `tab_reset` responsibility; global reset never repairs
job state, URL data, errors, enablement, or connections.
"""

from __future__ import annotations

from typing import Any

from app.browser.page_status import PageStatus, now_iso
from app.services.pool_status import publish_pool_status
from app.services.run_state import batch_active


def _clear_decision(page: Any, preserve_pending: bool, settle: bool) -> tuple[int, bool]:
    """Read one page's timer/debt state and decide whether a reset changes it."""
    was = page.remaining_seconds()
    pending = max(int(getattr(page, "pending_penalty", 0) or 0), 0)
    timer_fields = any((page.cooldown_until, page.cooldown_total, page.cooldown_reason))
    changed = was > 0 or timer_fields or (pending > 0 and not preserve_pending) or settle
    return was, bool(changed)


def clear_cooldown_fields(page: Any, preserve_pending: bool = False,
                          settle: bool = False) -> tuple[int, bool]:
    """Clear one page's cooldown; optional row settle preserves legacy semantics."""
    was, changed = _clear_decision(page, preserve_pending, settle)
    if not changed:
        return was, False
    page.clear_timer()
    if not preserve_pending:
        page.pending_penalty = 0
    if settle:
        page.status, page.current_job_id = PageStatus.STEADY, None
        page.last_steady_at, page.error = now_iso(), None
    elif page.status == PageStatus.COOLDOWN and not preserve_pending:
        page.status, page.last_steady_at = PageStatus.STEADY, now_iso()
    return was, True


def _reset_rows(pool: Any, live_run: bool) -> tuple[list, list, list]:
    """Apply one locked batch; return changed, failed, and protected worker ids."""
    reset, failed, deferred = [], [], []
    with pool._lock:
        for tab_id, page in list(pool._pages.items()):
            try:
                preserve = live_run and bool(getattr(page, "current_image", None))
                if preserve and int(page.pending_penalty or 0) > 0:
                    deferred.append(tab_id)
                _was, changed = clear_cooldown_fields(page, preserve_pending=preserve)
                if changed:
                    reset.append(tab_id)
            except Exception:
                failed.append(tab_id)
    return reset, failed, deferred


def reset_all_cooldowns(bridge: Any) -> dict:
    """Reset current pooled cooldowns, then persist and push one readiness snapshot."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return {"ok": False, "error": "pool not initialized"}
    try:
        reset, failed, deferred = _reset_rows(pool, batch_active(bridge))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    persisted = publish_pool_status(bridge) if reset or failed else True
    return {"ok": True, "reset": len(reset), "reset_tab_ids": reset,
            "failed_tab_ids": failed, "deferred_tab_ids": deferred,
            "persisted": persisted}
