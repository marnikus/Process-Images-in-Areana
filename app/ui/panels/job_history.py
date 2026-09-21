"""Job History panel — finished-job rows for the Job History window.

Owns the 2 history slots: thin slots delegate to module funcs. The display
limit arrives through the existing `save_settings` slot (`apply_history_limit`,
mirroring `apply_url_interval`) — no third slot. Imports go panels ->
services/core only.
"""

import json

from app.services import job_history
from app.ui.qt_compat import Slot


def history_payload_json(bridge) -> str:
    """Newest-first rows + limit + totals (never raises — worst case an empty log)."""
    try:
        return json.dumps(job_history.history_payload(bridge), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"entries": [], "limit": job_history.DEFAULT_LIMIT,
                           "total": 0, "next_job_no": 1, "error": str(e)})


def clear_history(bridge) -> str:
    """Empty the log, push the empty window, log one line (RULE 2)."""
    try:
        job_history.store_of(bridge).clear()
        job_history.emit_history(bridge)
        bridge._log("🗂 Job history cleared", "info")
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


class JobHistoryMixin:
    """Finished-job rows (`get_job_history`) + user clear (`clear_job_history`)."""

    @Slot(result=str)
    def get_job_history(self):
        """Payload JSON for the window's first paint and the limit inputs' restore."""
        return history_payload_json(self)

    @Slot(result=str)
    def clear_job_history(self):
        """Empty the log (job_no keeps counting — ids are never reused)."""
        return clear_history(self)
