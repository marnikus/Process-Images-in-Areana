# ideal-size: ~80 lines reason=S4 budget — one funnel + two queue repairs; the eligibility rule itself lives in core/run_scope (merge-note §2, one owner)
"""live/feed (S4) — the queue-write funnel + queue repairs.

`commit_queue` is the ONE tail every queue mutation ends in: recalc →
save → undo → emit → wake, returning the eligible count (I-49). The
eligibility rule is `core.run_scope.eligible_images` — processing is
never eligible; `recover_stale_processing` re-queues crash leftovers
first instead (hands off anything a pooled tab is actively working).
`clear_row_assignments` drops dangling URL links for the S6 row delete.
"""

from __future__ import annotations

from app.core.run_scope import eligible_images
from app.services.live.bus import live_bus


def commit_queue(bridge, reason: str, undo: bool = True) -> int:
    """The one queue-write funnel: recalc → save → undo → emit → wake."""
    bridge.state.recalculate_progress()
    bridge._save_arena()
    if undo:
        push = getattr(bridge, "_queue_undo_push", None)
        if push is not None:
            push(bridge)
    try:
        bridge._emit_arena_state()
    except Exception:
        pass  # bare hosts without the emitter still commit
    live_bus(bridge).wake(reason)
    return len(eligible_images(getattr(bridge.state, "images", None) or []))


def _live_image_names(pool) -> set:
    """Filenames pooled tabs are actively processing (empty without a pool)."""
    try:
        return {getattr(p, "current_image", None) for p in pool._pages.values()}
    except Exception:
        return set()


def recover_stale_processing(bridge) -> int:
    """Crash leftovers: `processing` with no live tab job → pending + selected."""
    live = _live_image_names(getattr(bridge, "_page_pool", None))
    count = 0
    for img in bridge.state.images:
        if img.status != "processing" or img.filename in live:
            continue  # live job on some tab: hands off
        img.status = "pending"
        img.selected = True
        img.error = None
        count += 1
    return count


def clear_row_assignments(bridge, row_ids) -> int:
    """Drop `assigned_url_id` links pointing at removed URL rows (S6)."""
    removed = set(row_ids)
    count = 0
    for img in bridge.state.images:
        if img.assigned_url_id in removed:
            img.assigned_url_id = None
            count += 1
    return count
