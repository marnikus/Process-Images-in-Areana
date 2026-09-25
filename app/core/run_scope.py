"""Run scope — which queue items a batch may claim (one predicate, RULE 10).

Owns "may this image be sent": `in_run_scope` = selected AND runnable
status. Two moments ask it — the batch start (`run_scope`) and, the part
that was missing until B13, every loop right before it claims an image
(`claim_denied`) — so an image that became `completed`/`skipped` or was
deselected after the list was built is never sent again (I-44). Both the
sequential loop (`batch_orchestrator`) and the parallel worker
(`multi_page_dispatcher`) call `claim_denied`; the run panel
(`run_control`) filters the batch with `run_scope`.

The live loop (S4/S5) asks the SAME module a narrower question —
`live_scope`: selected AND `LIVE_STATUSES`, which is `RUNNABLE_STATUSES`
without `processing` (a live loop must never dispatch an image twice; a
crash leftover is returned to `pending` by `live.feed.recover_stale_processing`
before the loop asks). A live run never ends (S5), so `failed` needs a
rest rule too: `settings.retries.max_attempts` caps automatic re-runs
(`in_live_scope(img, max_attempts)`); Retry / Reset return the image to
`pending`, which always runs. One owner, two moments, no copies (RULE 10, L-4).

Imports go core -> core only (no Qt, no services, no ui).
"""

from __future__ import annotations

from typing import Callable, Iterable, List

from .enums import ImageStatus

# `needs_review` is NOT runnable (Firefox image job D-15, 2026-09-25): the message
# may already have reached the site — a loop must never send it again; the user
# re-queues it deliberately (review → pending / selected).
RUNNABLE_STATUSES = frozenset({
    ImageStatus.PENDING.value,
    ImageStatus.SELECTED.value,
    ImageStatus.FAILED.value,
    ImageStatus.PROCESSING.value,   # crash leftovers are re-run, not stranded
})


# the live loop's rule: runnable minus `processing` (double-dispatch protection)
LIVE_STATUSES = RUNNABLE_STATUSES - {ImageStatus.PROCESSING.value}


def is_runnable(status: str) -> bool:
    """A status a loop may claim; `completed` / `skipped` / `deselected` / `needs_review` never are."""
    return status in RUNNABLE_STATUSES


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


def _attempts_left(img, max_attempts: int) -> bool:
    """`failed` rests once `attempt_count` reached the cap (0 = no cap); Retry / Reset (→ `pending`) always run."""
    if img.status != ImageStatus.FAILED.value or max_attempts <= 0:
        return True
    return int(getattr(img, "attempt_count", 0) or 0) < max_attempts


def in_live_scope(img, max_attempts: int = 0) -> bool:
    """The live loop's predicate: selected AND `LIVE_STATUSES` AND attempts left (S5 retry cap)."""
    return bool(img.selected) and img.status in LIVE_STATUSES and _attempts_left(img, max_attempts)


def live_scope(images: Iterable, max_attempts: int = 0) -> List:
    """Images the live loop may dispatch now (snapshot copy; never `processing`)."""
    return [img for img in images if in_live_scope(img, max_attempts)]
