"""live.feed — one claim scope, one queue-write funnel (S4, I-49).

`eligible_images` delegates to `core.run_scope.claim_scope` (no third rule);
`commit_queue` is the only way a queue write reaches disk, undo and the loop.
RULE 8: real PagePool + real `cooldown_service.set_tab_image`; the bridge is a
spy that records the order of its side effects.
"""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.core import run_scope
from app.core.enums import ImageStatus
from app.services import cooldown_service
from app.services.live import feed
from app.services.live.bus import live_bus
from tests.test_captcha_service import make_info

pytestmark = pytest.mark.unit


def img(name="a.png", status="pending", selected=True, assigned=None):
    return SimpleNamespace(relative_path=name, status=status, selected=selected,
                           error=None, assigned_url_id=assigned)


def spy_bridge(images):
    calls = []
    state = SimpleNamespace(images=list(images), jobs=[],
                            recalculate_progress=lambda: calls.append("recalc"))
    return SimpleNamespace(state=state, calls=calls,
                           _save_arena=lambda: calls.append("save+emit"),
                           _log=lambda m, l="info": calls.append(("log", m)))


def test_eligible_images_is_the_only_rule():
    items = [img(f"{s.value}.png", s.value, True) for s in ImageStatus]
    items.append(img("off.png", "pending", selected=False))
    before = list(items)
    picked = feed.eligible_images(items)
    assert [i.relative_path for i in picked] == ["pending.png", "selected.png", "failed.png",
                                                 "needs_review.png"]
    assert items == before and picked is not items          # snapshot copy, input untouched
    assert feed.ELIGIBLE is run_scope.CLAIMABLE_STATUSES
    assert picked == run_scope.claim_scope(items)


def test_claim_scope_is_run_scope_minus_in_flight_work():
    """Start counts a crash leftover (`processing`) as part of the run; a live pass never claims it."""
    assert run_scope.CLAIMABLE_STATUSES == run_scope.RUNNABLE_STATUSES - {"processing"}
    assert run_scope.is_claimable("processing") is False and run_scope.is_runnable("processing") is True
    items = [img("a", "pending"), img("b", "processing"), img("c", "failed")]
    assert [i.relative_path for i in run_scope.run_scope(items)] == ["a", "b", "c"]
    assert [i.relative_path for i in run_scope.claim_scope(items)] == ["a", "c"]


def test_commit_queue_recalculates_saves_pushes_undo_and_wakes():
    bridge = spy_bridge([img("a", "pending"), img("b", "completed"), img("c", "failed", selected=False)])
    undo = lambda b: bridge.calls.append("undo")  # noqa: E731 — the panel's push_queue_undo stands in
    count = feed.commit_queue(bridge, "reset_all", undo=undo)
    assert bridge.calls == ["recalc", "save+emit", "undo"]   # in that order, nothing else
    assert live_bus(bridge).reasons() == ["reset_all"]        # ...and then the wake
    assert count == 1                                         # the claimable count


def test_commit_queue_without_undo_pushes_nothing():
    bridge = spy_bridge([img("a", "pending")])
    assert feed.commit_queue(bridge, "scan") == 1
    assert bridge.calls == ["recalc", "save+emit"]
    assert live_bus(bridge).reasons() == ["scan"]


def test_recover_stale_processing_skips_live_jobs():
    pool = PagePool()
    pool.add_page(make_info("t1"))
    cooldown_service.set_tab_image(pool, "t1", "busy.png")
    live = img("dir/busy.png", "processing")
    stale = img("dir/stale.png", "processing", selected=False)
    done = img("done.png", "completed")
    bridge = spy_bridge([live, stale, done])
    bridge._page_pool = pool
    assert feed.recover_stale_processing(bridge) == 1
    assert (live.status, live.selected) == ("processing", True)     # a live tab job is left alone
    assert (stale.status, stale.selected, stale.error) == ("pending", True, None)
    assert done.status == "completed"
    assert feed.recover_stale_processing(SimpleNamespace(state=bridge.state, _page_pool=None)) == 1  # no pool: nothing is live


def test_clear_row_assignments_only_touches_the_removed_rows():
    a, b, c = img("a", assigned="u1"), img("b", assigned="u2"), img("c", assigned=None)
    bridge = spy_bridge([a, b, c])
    assert feed.clear_row_assignments(bridge, {"u1", "u9"}) == 1
    assert (a.assigned_url_id, b.assigned_url_id, c.assigned_url_id) == (None, "u2", None)
    assert feed.clear_row_assignments(bridge, set()) == 0


async def test_commit_queue_is_thread_safe_from_a_worker():
    """A scan worker commits from its own thread: the state lock is held around the write,
    the funnel never awaits (so the lock is never held across a coroutine boundary), and the
    wake still reaches the loop thread."""
    bridge = spy_bridge([img("a", "pending")])
    owned = []
    bridge._save_arena = lambda: owned.append(feed.state_lock(bridge)._is_owned())
    bus = live_bus(bridge)
    bus.attach(asyncio.get_running_loop())
    assert not asyncio.iscoroutinefunction(feed.commit_queue)
    worker = threading.Thread(target=feed.commit_queue, args=(bridge, "scan"))
    worker.start()
    assert await asyncio.wait_for(bus.wait(5), timeout=2) == "scan"
    worker.join(timeout=2)
    assert owned == [True]
    assert feed.state_lock(bridge)._is_owned() is False   # released after the write
