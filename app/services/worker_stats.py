"""Exact worker-counter edits and restore precedence.

The worker counter remains display-only. This service mutates only
`PageInfo.jobs_completed`; pool snapshots persist it through `cooldown_store`.
"""

from __future__ import annotations

import re
from typing import Any

from app.persistence.cooldown_store import worker_stats_key


def _count_at(stats: dict, key: str) -> int | None:
    """Valid saved whole count at one key, or None when absent/malformed."""
    row = stats.get(key) if isinstance(stats, dict) else None
    value = row.get("jobs_completed") if isinstance(row, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _restored_count(page: Any, tab_id: str, norm_url: str, stats: dict) -> int:
    """An exact worker correction wins; old URL maxima remain the fallback."""
    exact = _count_at(stats, worker_stats_key(tab_id))
    if exact is not None:
        return exact
    saved = _count_at(stats, norm_url) or 0
    return max(page.jobs_completed, saved)


def restore_page_stats(pool: Any, tab_id: str, norm_url: str, stats: dict) -> int:
    """Restore one worker's display count; a manual override may lower it."""
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is None:
                return -1
            page.jobs_completed = _restored_count(page, tab_id, norm_url, stats)
            return page.jobs_completed
    except AttributeError:
        return -1


def _parse_count(raw: str) -> int | None:
    """Only an ASCII decimal whole number is a valid edited count."""
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+", raw):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def set_page_job_count(pool: Any, tab_id: str, raw_count: str) -> dict:
    """Set the display counter only; no job, queue, or URL state is touched."""
    count = _parse_count(raw_count)
    if pool is None:
        return {"ok": False, "error": "pool not initialized"}
    if count is None:
        return {"ok": False, "error": "count must be a whole non-negative number"}
    try:
        with pool._lock:
            page = pool._pages.get(tab_id)
            if page is None:
                return {"ok": False, "error": "unknown tab"}
            if page.jobs_completed == count:
                return {"ok": True, "changed": False, "count": str(count)}
            page.jobs_completed = count
            return {"ok": True, "changed": True, "count": str(count)}
    except AttributeError:
        return {"ok": False, "error": "pool unavailable"}


def edit_page_job_count(bridge: Any, tab_id: str, raw_count: str) -> dict:
    """Persist/push one changed display count; unchanged edits have no side effects."""
    pool = getattr(bridge, "_page_pool", None)
    result = set_page_job_count(pool, tab_id, raw_count)
    if not result.get("ok") or not result.get("changed"):
        if result.get("ok"):
            result["persisted"] = True
        return result
    from app.services.pool_status import publish_pool_status
    result["persisted"] = publish_pool_status(bridge)
    page = pool.get_page(tab_id)
    label = getattr(page, "label", tab_id)
    message = f"Jobs completed for {label} set to {result['count']}"
    level = "info" if result["persisted"] else "warn"
    if not result["persisted"]:
        message = f"⚠ {message}; value is live but could not be persisted"
    try:
        bridge._log(message, level)
    except Exception:
        pass
    return result
