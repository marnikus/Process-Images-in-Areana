# Integration/contract lane: real collaborators; not counted as function units.
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

from app.services.live.feed import commit_queue
from app.services.live.bus import live_bus

import pytest

pytestmark = pytest.mark.integration


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
