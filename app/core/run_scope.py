"""Run scope — which queue items a batch may claim (one predicate, RULE 10).

Owns the status side of "should this image be sent". Two moments ask it:
the batch start (`run_scope`) and — the part that was missing until B13 —
every loop right before it claims an image (`claim_denied`), so an image
that became `completed`/`skipped` after the list was built is never sent
again (I-44). Both the sequential loop (`batch_orchestrator`) and the
parallel worker (`multi_page_dispatcher`) call the same two functions and
the run panel (`run_control`) filters the batch with `run_scope`.

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


def run_scope(images: Iterable) -> List:
    """Images in run scope: selected AND runnable — the single predicate."""
    return [img for img in images if img.selected and is_runnable(img.status)]


def claim_denied(img, log: Callable[[str, str], None]) -> bool:
    """Claim-time re-check (I-44): True — and one `⏭` line — when `img` must not be sent."""
    if is_runnable(img.status):
        return False
    log(f"⏭ Skipping {img.relative_path} — already {img.status}", "info")
    return True
