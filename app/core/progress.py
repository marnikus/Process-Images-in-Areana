"""Progress counts for the image queue — the predicate table behind
`AppState.recalculate_progress` (extracted from `models.py` when it crossed
the RULE 18 file band; the queue shapes and the counting change for
different reasons).

Pure functions over the queue: how many images are selected, how many are
pending for the run, how many sit in each reported status. Imports go
core -> core only (no Qt, no services, no ui).
"""
from __future__ import annotations

from typing import Dict, Sequence

from .enums import ImageStatus

# progress key -> the status it counts (the predicate table)
_STATUS_KEYS = {
    "processing": ImageStatus.PROCESSING.value,
    "completed": ImageStatus.COMPLETED.value,
    "skipped": ImageStatus.SKIPPED.value,
    "failed": ImageStatus.FAILED.value,
    "needs_review": ImageStatus.NEEDS_REVIEW.value,
}
_PENDING_STATUSES = frozenset({ImageStatus.PENDING.value, ImageStatus.SELECTED.value})


def count_selected(images: Sequence) -> int:
    return sum(1 for img in images if img.selected)


def count_by_status(images: Sequence, status_value: str) -> int:
    return sum(1 for img in images if img.status == status_value)


def count_pending_selected(images: Sequence) -> int:
    """Selected images the run has not touched yet (`pending` / `selected`)."""
    return sum(1 for img in images if img.selected and img.status in _PENDING_STATUSES)


def build_progress_counts(images: Sequence) -> Dict[str, int]:
    """The progress dict the UI shows: total, selected, pending + one key per status in `_STATUS_KEYS`."""
    counts = {
        "total": len(images),
        "selected": count_selected(images),
        "pending": count_pending_selected(images),
    }
    for key, status_value in _STATUS_KEYS.items():
        counts[key] = count_by_status(images, status_value)
    return counts
