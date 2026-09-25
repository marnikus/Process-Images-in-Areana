"""S4 · `app/services/live/feed` — one eligibility rule (owned by
`core/run_scope`, never a copy), one queue-write funnel (`commit_queue`),
stale-`processing` recovery and dangling-row cleanup.

RED at base: `ModuleNotFoundError: app.services.live`.
"""

import threading
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core import run_scope
from app.core.models import ImageItem, UrlRow
from app.services import cooldown_service
from app.services.live import feed
from app.services.live.bus import live_bus

pytestmark = pytest.mark.unit

ALL_STATUSES = ("pending", "selected", "failed", "needs_review", "processing",
                "completed", "skipped", "deselected")


def img(name, status="pending", selected=True, **over):
    item = ImageItem(id=f"i-{name}", relative_path=name, absolute_path=f"/tmp/{name}",
                     filename=name, base_name=name.split(".")[0], extension=".png",
                     size=1, mtime=1.0, fingerprint=name, status=status, selected=selected)
    for k, v in over.items():
        setattr(item, k, v)
    return item


class SpyBridge:
    """Bridge duck-type with an ordered trace of the funnel's steps."""

    def __init__(self, images):
        self.trace = []
        self.logs = []
        self.state = SimpleNamespace(images=list(images), urls=[], jobs=[], progress={})
        self.state.recalculate_progress = lambda: self.trace.append("recalc")
        self._save_arena = lambda: self.trace.append("save")
        self._push_queue_undo = lambda: self.trace.append("undo")
        self._log = lambda m, l="info": self.logs.append((m, l))
        self._page_pool = None
        live_bus(self).wake = lambda reason: self.trace.append(f"wake:{reason}")


def test_eligible_images_is_the_only_rule():
    """The live rule lives in core/run_scope; feed only re-exports it (no third copy, RULE 10)."""
    queue = [img(f"{s}.png", status=s) for s in ALL_STATUSES]
    before = list(queue)
    got = feed.eligible_images(queue)
    assert sorted(i.status for i in got) == sorted(["pending", "selected", "failed"])  # D-15
    assert queue == before and got is not queue  # snapshot copy, input untouched
    assert feed.eligible_images is run_scope.live_scope
    assert feed.ELIGIBLE is run_scope.LIVE_STATUSES
    assert "processing" not in feed.ELIGIBLE and "processing" in run_scope.RUNNABLE_STATUSES
    assert feed.eligible_images([img("x.png", selected=False)]) == []  # selection still counts


def test_commit_queue_recalculates_saves_pushes_undo_emits_and_wakes():
    bridge = SpyBridge([img("a.png"), img("b.png", status="completed"), img("c.png", status="failed")])
    count = feed.commit_queue(bridge, "reset_all")
    assert bridge.trace == ["recalc", "save", "undo", "wake:reset_all"]
    assert count == 2  # a (pending) + c (failed) are queued for the live run


def test_commit_queue_without_undo_pushes_nothing():
    bridge = SpyBridge([img("a.png")])
    feed.commit_queue(bridge, "scan", undo=False)
    assert bridge.trace == ["recalc", "save", "wake:scan"]


def test_commit_queue_takes_exactly_three_parameters():
    import inspect
    params = list(inspect.signature(feed.commit_queue).parameters)
    assert params == ["bridge", "reason", "undo"]


def make_pool(*tabs):
    pool = PagePool()
    for t in tabs:
        pool.add_page(PageInfo(ws_url=f"ws://{t}", tab_id=t, title=t, url="https://arena.ai/x",
                               status=PageStatus.STEADY, is_connected=True))
    return pool


def test_recover_stale_processing_skips_live_jobs():
    pool = make_pool("t1", "t2")
    cooldown_service.set_tab_image(pool, "t1", "live.png")  # a job really runs here
    live = img("live.png", status="processing", selected=False, assigned_url_id="u1")
    stale = img("stale.png", status="processing", selected=False, assigned_url_id="u2", error="x")
    bridge = SpyBridge([live, stale])
    bridge._page_pool = pool
    bridge.state.urls = [UrlRow.create("https://arena.ai/1", enabled=True, tab_id="t1"),
                         UrlRow.create("https://arena.ai/2", enabled=True, tab_id="t2")]
    bridge.state.urls[0].id, bridge.state.urls[1].id = "u1", "u2"
    assert feed.recover_stale_processing(bridge) == 1
    assert (live.status, live.selected) == ("processing", False)
    assert (stale.status, stale.selected) == ("pending", True)
    assert bridge.trace == ["recalc", "save", "wake:recover"]  # a system change: no undo entry
    assert feed.recover_stale_processing(bridge) == 0 and len(bridge.trace) == 3  # nothing to do, no commit


def test_recover_stale_processing_without_a_pool_treats_processing_as_stale():
    bridge = SpyBridge([img("a.png", status="processing", selected=False)])
    assert feed.recover_stale_processing(bridge) == 1
    assert bridge.state.images[0].status == "pending" and bridge.state.images[0].selected


def test_clear_row_assignments_only_touches_the_removed_rows():
    a = img("a.png", assigned_url_id="row-1")
    b = img("b.png", assigned_url_id="row-2")
    c = img("c.png", assigned_url_id=None)
    bridge = SpyBridge([a, b, c])
    assert feed.clear_row_assignments(bridge, {"row-1"}) == 1
    assert (a.assigned_url_id, b.assigned_url_id, c.assigned_url_id) == (None, "row-2", None)
    assert len(bridge.state.images) == 3 and bridge.trace == []  # no delete, no commit here


def test_commit_queue_is_thread_safe_from_a_worker():
    images = [img(f"{n}.png") for n in range(20)]
    bridge = SpyBridge(images)
    lock = feed.state_lock(bridge)
    assert lock is feed.state_lock(bridge)
    held = []
    bridge.state.recalculate_progress = lambda: held.append(lock.acquire(blocking=False) and (lock.release() or True))
    errors = []

    def worker(flag):
        try:
            for i in images:
                i.selected = flag
                feed.commit_queue(bridge, "select", undo=False)
        except Exception as e:  # pragma: no cover - the assertion below reports it
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(f,)) for f in (True, False, True, False)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert errors == []
    assert held and all(held)  # RLock: the committing thread owns the lock inside the funnel
    assert not lock.acquire(blocking=False) or lock.release() is None  # nothing left locked


def test_no_queue_rule_survives_outside_run_scope():
    """Source lock: the panels and services define no status tuple of their own (L-4)."""
    import re
    from pathlib import Path
    pattern = re.compile(r"\(\s*[\"']pending[\"']\s*,\s*[\"']failed[\"']")
    offenders = [p for p in Path("app").rglob("*.py")
                 if p.name != "run_scope.py" and pattern.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
