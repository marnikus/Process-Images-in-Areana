"""Live queue feed — ONE funnel for every queue mutation (D-6R), ONE eligibility
rule, ONE stale-processing recovery.

`eligible_images` is not a rule clone: it delegates to the single run-scope
predicate (`core.run_scope`, I-44) minus in-flight `processing` rows — the live
loop never re-dispatches an image a live tab job owns; crash leftovers are not
stranded because `recover_stale_processing` demotes them at every batch/live
start (L-4 killed by construction).

Every queue mutation (Reset, Reset All, Retry, Retry Failed, select/bulk-select,
clear, scan, preset load) ends in `commit_queue`, which recalculates, saves,
pushes undo (through a hook the panel layer registers — services never import
ui), and wakes the loop. `undo=False` keeps system writes (scan merges, preset
loads, clear's pre-pushed snapshot) out of the user's undo history (I-37).
"""

from __future__ import annotations

import os
from contextlib import nullcontext
from typing import Any, Callable, Optional

from app.core.enums import ImageStatus
from app.core.run_scope import in_run_scope

from .bus import live_bus

_UNDO_HOOK: Optional[Callable[[Any], None]] = None     # app.ui.panels.queue_scan registers push_queue_undo


def set_undo_hook(fn) -> None:
    """Install the panel layer's undo push (once, at panel import)."""
    global _UNDO_HOOK
    _UNDO_HOOK = fn


def eligible_images(images) -> list:
    """Live feed snapshot: run scope minus in-flight processing (D-6R, L-4)."""
    return [img for img in list(images)
            if in_run_scope(img) and img.status != ImageStatus.PROCESSING.value]


def commit_queue(bridge, reason: str, undo: bool = True) -> int:
    """The one funnel: recalc → save → undo → wake. Returns the eligible count."""
    lock = getattr(bridge, "_state_lock", None)
    with lock if lock is not None else nullcontext():
        bridge.state.recalculate_progress()
    bridge._save_arena()
    if undo and _UNDO_HOOK is not None:
        _UNDO_HOOK(bridge)
    count = len(eligible_images(bridge.state.images))
    live_bus(bridge).wake(reason)
    return count


def recover_stale_processing(bridge) -> int:
    """Crash leftovers come back: `processing` with no live tab job → pending+selected."""
    live = _live_basenames(getattr(bridge, "_page_pool", None))
    count = 0
    for img in bridge.state.images:
        if img.status != ImageStatus.PROCESSING.value:
            continue
        if os.path.basename(getattr(img, "relative_path", "") or "") not in live:
            img.status = ImageStatus.PENDING.value
            img.selected = True
            count += 1
    return count


def clear_row_assignments(bridge, row_ids) -> int:
    """Drop `assigned_url_id` values pointing at removed URL rows (S6 reconciler)."""
    count = 0
    for img in bridge.state.images:
        if getattr(img, "assigned_url_id", None) in row_ids:
            img.assigned_url_id = None
            count += 1
    return count


def reset_to_pending(img) -> None:
    """D-6R's one mutation: pending + re-selected, evidence cleared."""
    img.status = ImageStatus.PENDING.value
    img.selected = True
    img.error = None
    img.output_path = None
    img.assigned_url_id = None
    img.attempt_count = 0


def _live_basenames(pool) -> set:
    """Basenames the pool's tabs currently claim as their live job."""
    try:
        pages = list(getattr(pool, "_pages", {}).values())
    except Exception:
        return set()
    return {name for name in (getattr(p, "current_image", None) for p in pages) if name}
