"""S4 — live feed: one funnel for queue writes, one eligibility rule, one recovery."""

import threading
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.services import cooldown_service
from app.services.live import feed
from app.services.live.bus import live_bus
from tests.test_multi_page_dispatcher_run import make_img

pytestmark = pytest.mark.unit


def named(name, **kw):
    """make_img + post-construction mutations it doesn't accept."""
    status = kw.pop("status", None)
    assigned = kw.pop("assigned_url_id", None)
    error = kw.pop("error", None)
    kw.setdefault("selected", True)
    img = make_img(name, **kw)
    if status is not None:
        img.status = status
    if assigned is not None:
        img.assigned_url_id = assigned
    if error is not None:
        img.error = error
    return img


def state_with(images, calls=None):
    st = SimpleNamespace(images=list(images))
    st.recalculate_progress = lambda: calls is not None and calls.append("recalc")
    return st


def bridge_with(images, undo_store=None):
    calls = []
    st = state_with(images, calls)
    stored = undo_store if undo_store is not None else calls
    undo = SimpleNamespace(push=lambda kind, value: stored.append(("undo", kind)))
    b = SimpleNamespace(state=st, _save_arena=lambda: calls.append("save"),
                        undo_service=undo, _log=lambda m, l="info": None)
    return b, calls


@pytest.fixture
def undo_hook(monkeypatch):
    """Real queue-scan undo hook shape, isolated per test (module attr)."""
    hooked = []

    def hook(bridge):
        bridge.undo_service.push("queue", None)

    monkeypatch.setattr(feed, "_UNDO_HOOK", hook)
    hooked.append(hook)
    return hooked


def test_eligible_images_is_the_one_rule_minus_in_flight():
    queue = [named("pending.png", status="pending"),
             named("failed.png", status="failed"),
             named("selected.png", status="selected"),
             named("review.png", status="needs_review"),
             named("processing.png", status="processing"),
             named("completed.png", status="completed"),
             named("skipped.png", status="skipped"),
             named("deselected.png", status="pending", selected=False)]
    got = feed.eligible_images(queue)
    assert [i.filename for i in got] == ["pending.png", "failed.png", "selected.png", "review.png"]
    assert len(queue) == 8                     # the argument list is not mutated
    assert queue[0].filename == "pending.png"


def test_eligible_is_run_scope_minus_processing_no_clone():
    """L-4 killed by delegation: if either rule copy comes back the equality fails."""
    from app.core.run_scope import in_run_scope

    queue = [named("p.png", status="pending"), named("pr.png", status="processing"),
             named("f.png", status="failed"), named("c.png", status="completed")]
    expected = [i for i in queue
                if in_run_scope(i) and i.status != "processing"]
    assert feed.eligible_images(queue) == expected


def test_commit_queue_recalc_save_undo_wake_in_order(undo_hook):
    b, calls = bridge_with([named("a.png"), named("b.png"), named("c.png", status="completed")])
    count = feed.commit_queue(b, "reset_all")
    assert count == 2                                            # eligible (pending) count
    assert calls == ["recalc", "save", ("undo", "queue")]       # recalc → save → undo …
    assert live_bus(b).reasons() == ["reset_all"]               # … → wake (drained once)


def test_commit_queue_without_undo_pushes_nothing(undo_hook):
    b, calls = bridge_with([named("a.png")])
    feed.commit_queue(b, "scan", undo=False)
    assert ("undo", "queue") not in calls                       # system writes stay out of history (I-37)
    assert calls == ["recalc", "save"]
    assert live_bus(b).reasons() == ["scan"]


def test_recover_stale_processing_skips_live_jobs_only():
    pool = PagePool()
    pool.add_page(_pi("t1"))
    cooldown_service.set_tab_image(pool, "t1", "live.png")
    live_img = named("in/dir/live.png", status="processing")
    stale_img = named("in/dir/stale.png", status="processing")
    b, _ = bridge_with([live_img, stale_img])
    b._page_pool = pool
    count = feed.recover_stale_processing(b)
    assert count == 1
    assert live_img.status == "processing"                       # a live tab owns it
    assert stale_img.status == "pending" and stale_img.selected is True


def test_clear_row_assignments_only_touches_the_removed_rows():
    keep = named("keep.png", assigned_url_id="row-9")
    drop = named("drop.png", assigned_url_id="row-5")
    b, _ = bridge_with([keep, drop])
    n = feed.clear_row_assignments(b, {"row-5"})
    assert n == 1
    assert keep.assigned_url_id == "row-9"
    assert drop.assigned_url_id is None


def test_commit_queue_from_a_worker_thread_is_safe(undo_hook):
    b, calls = bridge_with([named(f"{i}.png") for i in range(50)])
    b._state_lock = threading.RLock()
    errors = []
    results = []

    def work():
        try:
            results.append(feed.commit_queue(b, "scan", undo=False))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert all(r == 50 for r in results)                          # no torn snapshot


def _pi(tab_id):
    from app.browser.page_status import PageInfo, PageStatus

    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=tab_id,
                    url="https://x", status=PageStatus.STEADY, is_connected=True)
