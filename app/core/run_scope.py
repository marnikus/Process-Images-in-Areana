"""Run scope — which queue items a batch may claim (one predicate, RULE 10).

Owns "may this image be sent": `in_run_scope` = selected AND runnable
status. Two moments ask it — the batch start (`run_scope`) and, the part
that was missing until B13, every loop right before it claims an image
(`claim_denied`) — so an image that became `completed`/`skipped` or was
deselected after the list was built is never sent again (I-44). Both the
sequential loop (`batch_orchestrator`) and the parallel worker
(`multi_page_dispatcher`) call `claim_denied`; the run panel
(`run_control`) filters the batch with `run_scope`.

Imports go core -> core only (no Qt, no services, no ui).
"""

from __future__ import annotations

from typing import Callable, Iterable, List

from .enums import ImageStatus

RUNNABLE_STATUSES = frozenset({
    ImageStatus.PENDING.value,
    ImageStatus.SELECTED.value,
    ImageStatus.FAILED.value,
    ImageStatus.NEEDS_REVIEW.value,
    ImageStatus.PROCESSING.value,   # crash leftovers are re-run, not stranded
})


def is_runnable(status: str) -> bool:
    """A status a loop may claim; `completed` / `skipped` / `deselected` never are."""
    return status in RUNNABLE_STATUSES


# The batch-planning set (S4, I-49): runnable minus `processing`. Crash
# leftovers re-enter through `live.feed.recover_stale_processing` before
# planning; live `processing` is never double-dispatched.
ELIGIBLE_STATUSES = RUNNABLE_STATUSES - {ImageStatus.PROCESSING.value}


def eligible_images(images: Iterable) -> List:
    """Images the next pass may plan, in queue order (selected + eligible)."""
    return [img for img in images if bool(img.selected) and img.status in ELIGIBLE_STATUSES]


def in_run_scope(img) -> bool:
    """The single predicate: selected AND a runnable status (RULE 10)."""
    return bool(img.selected) and is_runnable(img.status)


def run_scope(images: Iterable) -> List:
    """Images a batch may send, in queue order."""
    return [img for img in images if in_run_scope(img)]


def claim_denied(img, log: Callable[[str, str], None]) -> bool:
    """Claim-time re-check (I-44): True — and one `⏭` line — when `img` must not be sent."""
    if in_run_scope(img):
        return False
    why = f"already {img.status}" if not is_runnable(img.status) else "deselected"
    log(f"⏭ Skipping {img.relative_path} — {why}", "info")
    return True
