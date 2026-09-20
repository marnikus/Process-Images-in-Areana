# ideal-size: ~190 lines reason=S4 RED budget — funnel/stale-recovery spy tests (tdd-interfaces rev-3, 7 tests)
"""live/feed (S4) — one eligibility rule, one queue-write funnel, stale recovery.

Spec: `commit_queue(bridge, reason, undo=True)` = recalc → save → undo →
emit → wake, returns the eligible count; `recover_stale_processing` never
touches an image whose tab has a live job; `clear_row_assignments` drops
dangling URL links. The eligibility rule lives in `core/run_scope`
(merge-note §2: never a third rule) — `processing` is never eligible.
"""

import asyncio
import threading
from types import SimpleNamespace

from app.core.run_scope import eligible_images
from app.services.live.feed import (
    clear_row_assignments,
    commit_queue,
    recover_stale_processing,
)
from app.services.live.bus import live_bus


def _img(i, status="pending", selected=True, assigned=None, filename=None):
    return SimpleNamespace(id=f"i{i}", filename=filename or f"i{i}.png",
                           status=status, selected=selected, error="old" if status == "failed" else None,
                           assigned_url_id=assigned, relative_path=f"i{i}.png")


class SpyState:
    def __init__(self, images):
        self.images = images
        self.recalcs = 0

    def recalculate_progress(self):
        self.recalcs += 1


class SpyBridge:
    """Bridge duck-type: records save/emit/undo; pool optional."""

    def __init__(self, images, pool=None):
        self.state = SpyState(images)
        self.saves = 0
        self.emits = 0
        self.undo_pushes = []
        self._page_pool = pool
        self._queue_undo_push = lambda b: b.undo_pushes.append("queue")

    def _save_arena(self):
        self.saves += 1

    def _emit_arena_state(self):
        self.emits += 1


def test_eligible_never_includes_processing():
    statuses = ["pending", "failed", "selected", "needs_review",
                "processing", "skipped", "completed", "deselected"]
    images = [_img(i, status=s) for i, s in enumerate(statuses)]
    images.append(_img(99, status="pending", selected=False))
    got = eligible_images(images)
    assert [img.status for img in got] == ["pending", "failed", "selected", "needs_review"]
    assert all(img.selected for img in got)


def test_commit_queue_recalculates_saves_pushes_undo_emits_and_wakes():
    bridge = SpyBridge([_img(1, "pending"), _img(2, "processing"), _img(3, "completed")])
    count = commit_queue(bridge, "reset_all")
    assert bridge.state.recalcs == 1
    assert bridge.saves == 1
    assert bridge.undo_pushes == ["queue"]
    assert bridge.emits == 1
    assert live_bus(bridge).reasons() == ["reset_all"]
    assert count == 1  # pending + selected; processing/completed never eligible


def test_commit_queue_without_undo_pushes_nothing():
    bridge = SpyBridge([_img(1)])
    commit_queue(bridge, "scan", undo=False)
    assert bridge.undo_pushes == []  # system changes are not undoable (I-37)
    assert bridge.saves == 1 and bridge.emits == 1
    assert live_bus(bridge).reasons() == ["scan"]


def test_commit_queue_wakes_a_live_waiter():
    bridge = SpyBridge([_img(1)])

    async def main(loop):
        bus = live_bus(bridge)
        bus.attach(loop)
        task = asyncio.ensure_future(bus.wait(2.0))
        await asyncio.sleep(0.02)
        commit_queue(bridge, "reset_all")
        return await asyncio.wait_for(task, 3.0)

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(main(loop)) == "reset_all"
    finally:
        loop.close()


def test_commit_queue_is_thread_safe_from_a_worker():
    bridge = SpyBridge([_img(1)])
    bus = live_bus(bridge)
    barrier = threading.Barrier(4)
    errors = []

    def worker(n):
        try:
            barrier.wait()
            commit_queue(bridge, f"scan{n}", undo=False)
        except Exception as e:  # pragma: no cover - asserts the race stays clean
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors
    assert sorted(bus.reasons()) == ["scan0", "scan1", "scan2", "scan3"]


class _FakePage:
    def __init__(self, current_image):
        self.current_image = current_image


class _FakePool:
    def __init__(self, pages):
        self._pages = pages


def test_recover_stale_processing_revives_only_dead():
    live_img = _img(1, "processing", filename="live.png")
    dead_img = _img(2, "processing", filename="dead.png")
    done_img = _img(3, "completed", filename="done.png")
    pool = _FakePool({"t1": _FakePage("live.png")})
    bridge = SpyBridge([live_img, dead_img, done_img], pool=pool)

    count = recover_stale_processing(bridge)

    assert count == 1
    assert (live_img.status, live_img.selected) == ("processing", True)  # live job: hands off
    assert (dead_img.status, dead_img.selected, dead_img.error) == ("pending", True, None)
    assert done_img.status == "completed"


def test_clear_row_assignments_drops_removed_rows():
    bridge = SpyBridge([_img(1, assigned="u1"), _img(2, assigned="u2"), _img(3)])
    count = clear_row_assignments(bridge, ["u1"])
    assert count == 1
    assert bridge.state.images[0].assigned_url_id is None
    assert bridge.state.images[1].assigned_url_id == "u2"
