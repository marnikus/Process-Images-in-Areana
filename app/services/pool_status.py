"""Pool snapshot publish/read seam shared by bridge and panel services.

One push computes readiness, emits `page_pool_updated`, then saves one
cooldown/job-counter snapshot; UI panels remain outside this service.
"""

from __future__ import annotations

import json
from typing import Any

from app.services.cooldown_service import refresh_expired


def publish_pool_status(bridge: Any, snapshot: dict | None = None) -> bool:
    """Emit one snapshot and persist once; False means the snapshot did not save."""
    try:
        pool = getattr(bridge, "_page_pool", None)
        if pool is None:
            return False
        snap = snapshot if snapshot is not None else pool.status_snapshot()
        bridge.page_pool_updated.emit(json.dumps(snap, ensure_ascii=False))
        saved = bridge._persist_cooldowns()
        return saved is not False and getattr(bridge, "_persist_ok", True) is not False
    except Exception:
        return False


def get_page_pool_status(bridge: Any) -> str:
    """Refresh expired timers, report newly steady tabs, and return the snapshot."""
    try:
        pool = getattr(bridge, "_page_pool", None)
        if pool is None:
            return json.dumps({"total": 0, "steady": 0, "busy": 0,
                               "cooling": 0, "free": 0, "pages": []})
        _report_expired(bridge, pool)
        snap = pool.status_snapshot()
        publish_pool_status(bridge, snap)
        return json.dumps(snap, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _report_expired(bridge: Any, pool: Any) -> None:
    """One success line per timer that just expired; logger failure is harmless."""
    try:
        for tab_id in refresh_expired(pool):
            bridge._log(f"✅ Page {tab_id[:12]} cooldown expired — STEADY ready", "success")
    except Exception:
        pass
