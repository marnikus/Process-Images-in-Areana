"""Live feed — the one queue-write funnel and the live eligibility rule (S4).

* `eligible_images` / `ELIGIBLE` are **re-exports** of `core.run_scope`
  (`live_scope` / `LIVE_STATUSES`): one owner of "may this image be sent",
  no copy here (RULE 10, L-4).
* `commit_queue(bridge, reason, undo=True)` is where every queue mutation
  ends — Reset, Reset All, Retry, Retry Failed, select / bulk-select, clear,
  scan, preset load: recalc → save (which emits, I-39) → undo (user changes
  only, I-37) → `wake(reason)`. Returns the number of queued (live-eligible)
  images so the caller can say it (RULE 2).
* `recover_stale_processing` returns crash leftovers (`processing` on no
  live tab) to `pending` + `selected`; `clear_row_assignments` drops
  dangling `assigned_url_id`s when URL rows go (S6).

Thread rules: `state_lock(bridge)` (an RLock) guards the sync part of a
commit — worker threads (scan) and the UI thread both write through here;
it is never held across an `await` (nothing here is async).
Imports: core + same package; the undo push goes through the bridge seam
`_push_queue_undo` (set by `ui.bridge_context`), so services stay ui-free.
"""

from __future__ import annotations

import os
import threading
from typing import Iterable, Set

from app.core.run_scope import LIVE_STATUSES, live_scope

from .bus import live_bus

ELIGIBLE = LIVE_STATUSES
eligible_images = live_scope


def state_lock(bridge) -> threading.RLock:
    """The bridge's queue write lock (created on first use; `init_run_state` pre-creates it)."""
    lock = getattr(bridge, "_state_lock", None)
    if lock is None:
        lock = threading.RLock()
        bridge._state_lock = lock
    return lock


def commit_queue(bridge, reason: str, undo: bool = True) -> int:
    """recalc → save(+emit) → undo (user changes only) → wake; returns the queued count."""
    with state_lock(bridge):
        bridge.state.recalculate_progress()
        bridge._save_arena()
        if undo:
            _push_undo(bridge)
        queued = len(eligible_images(bridge.state.images))
    live_bus(bridge).wake(reason)
    return queued


def _push_undo(bridge) -> None:
    """Queue snapshot into the user's history via the ui seam (best effort)."""
    push = getattr(bridge, "_push_queue_undo", None)
    if push is None:
        return
    try:
        push()
    except Exception:
        pass


def _live_images(bridge) -> Set[str]:
    """Basenames a pooled tab is processing right now (`set_tab_image`)."""
    pool = getattr(bridge, "_page_pool", None)
    if pool is None:
        return set()
    try:
        pages = pool.status_snapshot().get("pages", [])
    except Exception:
        return set()
    return {p.get("current_image") for p in pages if p.get("current_image")}


def recover_stale_processing(bridge) -> int:
    """`processing` with no live tab job → `pending` + `selected` (committed, no undo entry)."""
    live = _live_images(bridge)
    count = 0
    for img in bridge.state.images:
        if img.status != "processing" or os.path.basename(img.relative_path or "") in live:
            continue
        img.status, img.selected, img.error = "pending", True, None
        count += 1
    if count:
        commit_queue(bridge, "recover", undo=False)
    return count


def clear_row_assignments(bridge, row_ids: Iterable[str]) -> int:
    """Drop `assigned_url_id` for removed URL rows; never deletes an image; no commit."""
    gone = set(row_ids)
    count = 0
    for img in bridge.state.images:
        if img.assigned_url_id in gone:
            img.assigned_url_id = None
            count += 1
    return count
