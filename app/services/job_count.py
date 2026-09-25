"""Per-tab job counter for the Jobs columns (display only) — moved from
`cooldown_service` (2026-09-25) so the Firefox job's finish seam fits there
without growing that legacy file; `cooldown_service` re-exports both names.
"""

from __future__ import annotations

from typing import Any

from app.browser.page_status import now_iso


def register_job_done(pool: Any, tab_id: str) -> int:
    """Count one finished job for the Jobs columns (display only); -1 when unknown."""
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
