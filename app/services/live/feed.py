"""One eligibility rule + one queue-write funnel (S4, D-6R).

Eligibility composes `core.run_scope` (the single predicate, RULE 10) minus
`processing`: the live loop never double-dispatches — the crash case moves to
`recover_stale_processing`. Every queue mutation ends in `commit_queue`
(recalc → save → undo → emit → wake). The undo snapshot format stays a UI
contract: `ui.services` is imported lazily so services never statically
import UI (the static graph stays acyclic).
"""

from __future__ import annotations

from app.core.enums import ImageStatus
from app.core.run_scope import in_run_scope
from app.services.cooldown_service import tab_has_live_job

from .bus import live_bus

ELIGIBLE = (
    ImageStatus.PENDING.value,
    ImageStatus.FAILED.value,
    ImageStatus.SELECTED.value,
    ImageStatus.NEEDS_REVIEW.value,
)


def eligible_images(images):
    """Live-queue rule: in run scope and not processing (snapshot copy)."""
    return [img for img in list(images) if in_run_scope(img) and img.status in ELIGIBLE]


def push_queue_undo(bridge) -> None:
    """Snapshot image queue to undo (best effort; moved from queue_scan)."""
    try:
        from app.ui.services import arena_serialize, undo_entries
        js_images = arena_serialize.arena_to_js(bridge.state)["images"]
        bridge.undo_service.push("queue", js_images)
        undo_entries.emit_undo_state(bridge)
    except Exception:
        pass


def commit_queue(bridge, reason: str, undo: bool = True) -> int:
    """Recalc → save → undo → emit → wake; returns the pending count."""
    with bridge._state_lock:
        bridge.state.recalculate_progress()
        bridge._save_arena()
        if undo:
            push_queue_undo(bridge)
        bridge._emit_arena_state()
        pending = sum(1 for img in bridge.state.images if img.status == "pending")
    live_bus(bridge).wake(reason)
    return pending


def recover_stale_processing(bridge) -> int:
    """`processing` with no live tab job → `pending` + `selected` (D-6R)."""
    pool = getattr(bridge, "_page_pool", None)
    tabs = {row.id: row.tab_id for row in bridge.state.urls}
    count = 0
    for img in bridge.state.images:
        if img.status != ImageStatus.PROCESSING.value:
            continue
        if tab_has_live_job(pool, tabs.get(img.assigned_url_id)):
            continue
        img.status = ImageStatus.PENDING.value
        img.selected = True
        count += 1
    return count


def clear_row_assignments(bridge, row_ids) -> int:
    """Drop `assigned_url_id` pointing at removed rows; returns cleared count."""
    gone = set(row_ids)
    count = 0
    for img in bridge.state.images:
        if img.assigned_url_id in gone:
            img.assigned_url_id = None
            count += 1
    return count
