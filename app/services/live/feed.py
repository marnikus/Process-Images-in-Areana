"""Live feed — the claim scope of a pass and the ONE queue-write funnel (S4, I-49 / I-54).

* `eligible_images` delegates to `core.run_scope.claim_scope` — no third
  eligibility rule (I-44 owns the predicate; a live pass never lists
  in-flight `processing` work).
* `commit_queue` is the only way a queue mutation reaches disk, the UI,
  undo and the live loop: recalc → save (+emit) → undo → wake. Every
  slot, scan worker and preset loader ends in it. It is synchronous, so
  the state lock is never held across an `await`.
* `requeue_for_start` makes Start mean "run everything runnable": crash
  leftovers (`recover_stale_processing`) and selected `failed` /
  `needs_review` images become fresh `pending` work, through the funnel.
* `clear_row_assignments` drops dangling `assigned_url_id`s (S6 reconciler).

Layer: services → core only. The undo push is a ui-layer function
(`queue_scan.push_queue_undo`), so panels hand it in as `undo=`; system
writes (scan, preset, clear) pass nothing and stay out of the user's history.
"""
# ideal-size: ~100 lines reason=the queue-write funnel and the claim scope only; the pass
# lifecycle (supervisor) and the row policy (url_policy) are deliberately separate owners.

from __future__ import annotations

import os
import threading
from typing import Any, Callable, Iterable, List, Optional

from app.core.run_scope import CLAIMABLE_STATUSES, RETRY_ON_START, claim_scope, run_scope

from .bus import live_bus

ELIGIBLE = CLAIMABLE_STATUSES


def eligible_images(images: Iterable) -> List:
    """Images a pass may claim (selected + claimable), in queue order — a fresh list."""
    return claim_scope(images)


def state_lock(bridge: Any) -> threading.RLock:
    """The bridge's queue-write lock (created by `init_run_state`; lazily for bare hosts)."""
    lock = getattr(bridge, "_state_lock", None)
    if lock is None:
        lock = bridge._state_lock = threading.RLock()
    return lock


def commit_queue(bridge: Any, reason: str, undo: Optional[Callable[[Any], None]] = None) -> int:
    """The funnel: recalc → save (+emit) → undo (if given) → wake(reason). Returns the claimable count."""
    with state_lock(bridge):
        bridge.state.recalculate_progress()
        bridge._save_arena()
    if undo is not None:
        undo(bridge)
    live_bus(bridge).wake(reason)
    return len(eligible_images(bridge.state.images))


def _live_image_names(pool: Any) -> set:
    """Basenames currently running on a pooled tab (`current_image`, set by both run paths)."""
    try:
        return {p.get("current_image") for p in pool.status_snapshot()["pages"] if p.get("current_image")}
    except Exception:
        return set()


def recover_stale_processing(bridge: Any) -> int:
    """`processing` with no live tab job → pending + selected (a crash leftover, not a running job)."""
    live = _live_image_names(getattr(bridge, "_page_pool", None))
    count = 0
    for img in bridge.state.images:
        if img.status == "processing" and os.path.basename(img.relative_path or "") not in live:
            img.status, img.selected, img.error = "pending", True, None
            count += 1
    return count


def requeue_for_start(bridge: Any) -> int:
    """Start = run everything in run scope: leftovers and selected failed/needs_review → pending (committed)."""
    count = recover_stale_processing(bridge)
    for img in run_scope(bridge.state.images):
        if img.status in RETRY_ON_START:
            img.status, img.error = "pending", None
            count += 1
    if count:
        commit_queue(bridge, "start")
    return count


def clear_row_assignments(bridge: Any, row_ids: Iterable[str]) -> int:
    """Drop `assigned_url_id` for removed URL rows; returns how many images were unassigned."""
    gone = set(row_ids)
    count = 0
    for img in bridge.state.images:
        if img.assigned_url_id in gone:
            img.assigned_url_id = None
            count += 1
    return count
