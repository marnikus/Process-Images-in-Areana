"""Per-tab job counter for the Jobs columns (display only).

Finished jobs still increment `PageInfo.jobs_completed` here. Restore and
explicit inline correction live in `worker_stats.py`; cooldown_service
re-exports both public functions for its existing callers.
"""

from __future__ import annotations

from typing import Any

from app.browser.page_status import now_iso
from app.services.worker_stats import restore_page_stats


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
