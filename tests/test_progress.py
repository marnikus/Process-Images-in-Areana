"""core.progress — the queue's progress table (extracted from models, B13 validation pass).

RULE 8: real ImageItems through the real functions and through
`AppState.recalculate_progress`, which is the only production caller.
"""

from app.core.models import AppState, ImageItem
from app.core import progress


def item(name, status, selected):
    d = {"relative_path": name, "absolute_path": f"/x/{name}", "filename": name, "base_name": name,
         "extension": ".png", "size": 1, "mtime": 0.0, "fingerprint": f"fp-{name}", "id": f"id-{name}"}
    img = ImageItem.from_scan_dict(d)
    img.status, img.selected = status, selected
    return img


QUEUE = [item("a", "pending", True), item("b", "selected", True), item("c", "pending", False),
         item("d", "processing", True), item("e", "completed", True), item("f", "completed", False),
         item("g", "failed", True), item("h", "skipped", False), item("i", "needs_review", True)]


def test_progress_table_counts_each_key_from_the_real_queue():
    assert progress.build_progress_counts(QUEUE) == {
        "total": 9, "selected": 6, "pending": 2,
        "processing": 1, "completed": 2, "skipped": 1, "failed": 1, "needs_review": 1,
    }


def test_pending_means_selected_and_untouched_only():
    assert progress.count_pending_selected(QUEUE) == 2          # a (pending) + b (selected); c is deselected
    assert progress.count_selected(QUEUE) == 6
    assert progress.count_by_status(QUEUE, "completed") == 2     # regardless of the selected flag
    assert progress.build_progress_counts([]) == {"total": 0, "selected": 0, "pending": 0, "processing": 0,
                                                  "completed": 0, "skipped": 0, "failed": 0, "needs_review": 0}


def test_app_state_recalculate_uses_the_table():
    state = AppState()
    state.images = list(QUEUE)
    state.recalculate_progress()
    assert state.progress == progress.build_progress_counts(QUEUE)
    state.images[0].status = "completed"
    state.recalculate_progress()
    assert (state.progress["pending"], state.progress["completed"]) == (1, 3)
