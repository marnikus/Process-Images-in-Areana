"""Pool jobs panel — the JOBS count edit (I-64, 2026-09-25).

Owns ONE slot, `set_page_jobs`. The job count is a persistent display number
(never a routing input) that the user may correct from the pool table or the
URL list (`core/jobs-edit.js`). It lives in its own panel because the page-pool
mixin is at its frozen method budget (RULE 16 ratchet), the same way
`job_history` and `queue_scan_folder` carry their small surfaces.

The edit writes BOTH copies of the count: the live `PageInfo.jobs_completed`
and the stored stat (`cooldown_store.set_job_count`). The store merges counters
by max, so without the overwrite a lowered count would come back on the next
snapshot. Imports go panels → services/persistence/core only.
"""

import json

from app.persistence.cooldown_store import set_job_count
from app.services.run_state import cooldowns_path, tab_label_of
from app.ui.qt_compat import Slot

JOBS_MAX = 999_999


def edit_page_jobs(bridge, tab_id: str, count) -> dict:
    """Set one tab's job counter live AND in the store; a named refusal for an unknown tab."""
    pool = getattr(bridge, "_page_pool", None)
    page = pool.get_page(tab_id) if pool is not None else None
    if page is None:
        return {"ok": False, "error": "tab not in pool"}
    jobs = max(0, min(JOBS_MAX, int(count or 0)))
    with pool._lock:
        page.jobs_completed = jobs
    set_job_count(cooldowns_path(bridge), page.url, jobs)
    bridge._emit_pool_status()
    bridge._log(f"✏ Jobs for {tab_label_of(pool, tab_id)} set to {jobs}", "info")
    return {"ok": True, "jobs": jobs}


class PoolJobsMixin:
    """The JOBS edit slot (thin: the body is `edit_page_jobs`)."""

    @Slot(str, int, result=str)
    def set_page_jobs(self, tab_id: str, count: int):
        """JOBS edit (I-64): a persistent display count the user may correct."""
        try:
            return json.dumps(edit_page_jobs(self, tab_id, count), ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
