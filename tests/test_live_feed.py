"""S4: one eligibility rule + one queue-write funnel (live/feed).

T13 replaces the plan's `queue_scan.selected_images` delegation: that name no
longer exists — the L-4 clone already died to `core.run_scope` (pinned by
`test_run_scope.py` + `test_batch_orchestrator.py:426`), so eligibility composes
the single predicate instead of cloning it, and the test pins the equality.
"""

import asyncio
import os
import threading
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.core.enums import ImageStatus
from app.core.run_scope import run_scope
from app.services.cooldown_service import set_tab_image
from app.services.live.bus import live_bus
from app.services.live.feed import (
    ELIGIBLE,
    clear_row_assignments,
    commit_queue,
    eligible_images,
    recover_stale_processing,
)
from tests.characterization.harness import build_bridge, build_stack
from tests.test_captcha_service import make_info
from tests.test_multi_page_dispatcher_run import make_img


def _statuses(*names, selected=True):
    imgs = []
    for i, name in enumerate(names):
        img = make_img(f"{name or 'none'}-{i}.png", selected=selected)
        img.status = name
        imgs.append(img)
    return imgs


@pytest.mark.unit
def test_eligible_images_is_the_only_rule():
    imgs = _statuses("pending", "failed", "selected", "needs_review",
                     "processing", "completed", "skipped")
    before = [(img.id, img.status, img.selected) for img in imgs]
    out = eligible_images(imgs)
    assert sorted(img.status for img in out) == ["failed", "needs_review", "pending", "selected"]
    assert "processing" not in ELIGIBLE  # double-dispatch protection lives here
    assert all(img.selected for img in out)
    assert [(img.id, img.status, img.selected) for img in imgs] == before  # untouched
    assert out is not imgs  # snapshot copy


@pytest.mark.unit
def test_eligible_images_ignores_deselected_and_live_processing():
    pending_out = _statuses("pending", selected=False)[0]
    live_busy = _statuses("processing")[0]
    assert eligible_images([pending_out, live_busy]) == []


@pytest.mark.unit
def test_commit_queue_recalculates_saves_pushes_undo_emits_and_wakes(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=2)
    bridge = env.bridge
    bridge.state.images[1].status = ImageStatus.COMPLETED.value
    calls = []

    def _wrap(obj, name, label):
        real = getattr(obj, name)
        setattr(obj, name, lambda *a, **k: (calls.append(label), real(*a, **k))[1])

    _wrap(bridge.state, "recalculate_progress", "recalc")
    _wrap(bridge, "_save_arena", "save")
    _wrap(bridge.undo_service, "push", "undo")
    _wrap(bridge, "_emit_arena_state", "emit")
    _wrap(live_bus(bridge), "wake", "wake")

    assert commit_queue(bridge, "reset_all") == 1  # the pending count
    assert calls == ["recalc", "save", "undo", "emit", "wake"]
    assert live_bus(bridge).reasons() == ["reset_all"]


@pytest.mark.unit
def test_commit_queue_without_undo_pushes_nothing(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=1)
    bridge = env.bridge
    pushed = []
    real_push = bridge.undo_service.push
    bridge.undo_service.push = lambda *a, **k: (pushed.append(a), real_push(*a, **k))[1]
    assert commit_queue(bridge, "scan", undo=False) == 1  # system change (I-37)
    assert pushed == []
    assert live_bus(bridge).reasons() == ["scan"]  # the wake still fires


@pytest.mark.unit
def test_recover_stale_processing_skips_live_jobs(tmp_path):
    pool = PagePool()
    pool.add_page(make_info("t1"))
    pool.add_page(make_info("t2"))
    env = build_bridge(tmp_path, build_stack([]), n_images=0, pool=pool,
                       tab_ids=["t1", "t2"])
    bridge = env.bridge
    row1, row2 = bridge.state.urls
    live = make_img("live.png")
    live.status = ImageStatus.PROCESSING.value
    live.assigned_url_id = row1.id
    stale = make_img("stale.png")
    stale.status = ImageStatus.PROCESSING.value
    stale.assigned_url_id = row2.id
    orphan = make_img("orphan.png")
    orphan.status = ImageStatus.PROCESSING.value
    orphan.assigned_url_id = None
    done = make_img("done.png")
    done.status = ImageStatus.COMPLETED.value
    done.assigned_url_id = row1.id
    bridge.state.images = [live, stale, orphan, done]
    set_tab_image(pool, "t1", os.path.basename(live.relative_path))

    assert recover_stale_processing(bridge) == 2
    assert (live.status, live.selected) == ("processing", True)  # tab t1 runs it
    assert (stale.status, stale.selected) == ("pending", True)  # t2 has no job
    assert (orphan.status, orphan.selected) == ("pending", True)
    assert done.status == "completed"  # not processing: untouched


@pytest.mark.unit
def test_clear_row_assignments_only_touches_the_removed_rows():
    first = make_img("a.png")
    first.assigned_url_id = "gone"
    second = make_img("b.png")
    second.assigned_url_id = "kept"
    third = make_img("c.png")
    bridge = SimpleNamespace(state=SimpleNamespace(images=[first, second, third]))
    assert clear_row_assignments(bridge, ["gone"]) == 1
    assert (first.assigned_url_id, second.assigned_url_id, third.assigned_url_id) == (None, "kept", None)
    assert len(bridge.state.images) == 3  # drops assignments, never images


@pytest.mark.unit
def test_commit_queue_is_thread_safe_from_a_worker(tmp_path):
    import threading as _th

    env = build_bridge(tmp_path, build_stack([]), n_images=5)
    bridge = env.bridge
    real_lock = bridge._state_lock
    held = []
    worker_errors = []

    class _RecordingLock:
        """Wrapper (threading.RLock is a factory here, not subclassable)."""

        def __init__(self):
            self._inner = _th.RLock()

        def acquire(self, *a, **k):
            ok = self._inner.acquire(*a, **k)
            if ok:
                held.append(("ac", _th.get_ident()))
            return ok

        def release(self, *a, **k):
            held.append(("rel", _th.get_ident()))
            return self._inner.release(*a, **k)

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, *exc):
            self.release()
            return False

    bridge._state_lock = _RecordingLock()
    assert real_lock is not None  # the harness bridge carries a real lock (RULE 8)

    def worker():
        try:
            for _ in range(20):
                commit_queue(bridge, "scan", undo=False)
        except Exception as e:  # pragma: no cover — fails the test below
            worker_errors.append(e)

    thread = _th.Thread(target=worker, daemon=True)
    thread.start()
    for _ in range(20):
        snapshot = [(img.id, img.status) for img in bridge.state.images]
        assert len(snapshot) == 5 and all(isinstance(s, str) for _, s in snapshot)
    thread.join(timeout=30)
    assert worker_errors == []
    assert not thread.is_alive()
    assert len(bridge.state.images) == 5
    acs = [t for op, t in held if op == "ac"]
    rels = [t for op, t in held if op == "rel"]
    assert len(acs) == len(rels) and len(acs) >= 20  # every take released
    assert bridge._state_lock.acquire(blocking=False)  # free afterwards
    bridge._state_lock.release()
    assert not asyncio.iscoroutinefunction(commit_queue)  # sync: never held across an await


@pytest.mark.unit
def test_eligible_is_run_scope_without_processing():
    imgs = []
    for status in ("pending", "failed", "selected", "needs_review",
                   "processing", "completed", "skipped"):
        imgs.extend(_statuses(status, selected=True))
        imgs.extend(_statuses(status, selected=False))
    assert eligible_images(imgs) == [img for img in run_scope(imgs)
                                     if img.status != ImageStatus.PROCESSING.value]
    assert all(img.status != "processing" for img in eligible_images(imgs))
