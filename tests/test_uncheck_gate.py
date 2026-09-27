"""I-68: a worker whose URL row is unchecked never takes another job.

The report (2026-09-27): the user unchecked the Chrome URL while its tab was
finishing / cooling, yet the next two jobs went to that Chrome tab instead of
the two Firefox tabs. Root cause: every pass copied the checked-tab set ONCE
(`DispatchCtx.allowed`, `BatchCtx.allowed`) and the feeder pass stays open as
long as the queue has work, so an uncheck never reached the gate. Unchecking
does take a tab out of the pool — but not while its job is still on it
(deferred to the next reconcile), and on the job's "page free" wake the
feeder's synchronous acquire always beat that async reconcile.

The fix: the gate reads the checkbox LIVE (`auto_connect.live_allowed`) on
every acquire attempt — including every poll of a job already waiting — in
both lanes. RULE 8: real PagePool, real feeder, real membership gate; only
the job-runner seam is faked.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_status import PageStatus
from app.core.enums import ImageStatus
from app.services import auto_connect as ac
from app.services import multi_page_dispatcher as mpd
from app.services.live.bus import live_bus
from app.ui.panels import page_pool as page_pool_panel
from app.ui.panels.url_queue import enforce_pool_membership
from tests.test_multi_page_dispatcher_run import FakeBridge, make_img, make_pool, make_urls

pytestmark = pytest.mark.unit

TABS = ("chrome", "fx1", "fx2")


class Jobs:
    """Per-image hold: a job runs until its own `release(name)` (captcha / generation stand-in)."""

    def __init__(self):
        self.started: list = []
        self._gates: dict = {}

    def gate(self, name: str) -> asyncio.Event:
        return self._gates.setdefault(name, asyncio.Event())

    def release(self, *names: str) -> None:
        for name in names:
            self.gate(name).set()

    def tab_of(self, name: str) -> str:
        return next((t for f, t in self.started if f == name), "")

    def make_run(self):
        async def run(job_ctx):
            self.started.append((job_ctx.img.filename, job_ctx.tab_id))
            await self.gate(job_ctx.img.filename).wait()
            return False, "", None, None
        return run


@pytest.fixture
def jobs(monkeypatch):
    record = Jobs()

    async def no_baseline(ctrl):
        return {"outputs": []}

    async def finish(ctx):
        ctx.pool.mark_steady(ctx.tab_id)

    monkeypatch.setattr(mpd, "capture_baseline", no_baseline)
    monkeypatch.setattr(mpd, "run_blocks_for_image", record.make_run())
    monkeypatch.setattr(mpd, "finish_page_after_job", finish)
    monkeypatch.setattr(mpd, "cooldown_aware_timeout", lambda pool: 5.0)
    monkeypatch.setattr(page_pool_panel, "schedule_coro", lambda bridge, coro: coro.close())  # badge clear
    return record


def setup(names):
    """Bridge + pool with Chrome and two Firefox-style workers, all checked."""
    images = [make_img(n, id="i-" + n) for n in names]
    bridge = FakeBridge()
    bridge.state.images = list(images)
    bridge.state.settings = SimpleNamespace(retries={})
    bridge.state.urls = make_urls(list(TABS))
    pool = make_pool(list(TABS))
    for tab in TABS:
        pool.register_client(tab, object(), object())
    bridge._page_pool = pool
    return bridge, pool, images


def row(bridge, tab):
    return next(u for u in bridge.state.urls if u.tab_id == tab)


def uncheck(bridge, tab):
    """What `toggle_url` does: flip the live row, then the commit's membership gate."""
    row(bridge, tab).enabled = False
    enforce_pool_membership(bridge)


async def until(cond, timeout=1.0):
    async def poll():
        while not cond():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


def start_pass(bridge, pool, images):
    return asyncio.create_task(mpd.dispatch_parallel(bridge, pool, images))


@pytest.mark.asyncio
async def test_the_report_uncheck_while_chrome_finishes_sends_the_next_jobs_to_firefox(jobs):
    """Chrome unchecked while its job still runs (exit deferred) → d and e go to the Firefox tabs."""
    bridge, pool, images = setup(["a.png", "b.png", "c.png", "d.png", "e.png"])
    pass_task = start_pass(bridge, pool, images)
    await until(lambda: len(jobs.started) == 3)
    chrome_job = next(f for f, t in jobs.started if t == "chrome")

    uncheck(bridge, "chrome")
    assert pool.get_page("chrome") is not None, "precondition: the exit is deferred while the job runs"
    jobs.release(chrome_job)                      # Chrome finishes → steady → "page free" wake
    await asyncio.sleep(0.2)
    assert len(jobs.started) == 3, f"a job went to the unchecked Chrome tab: {jobs.started}"

    jobs.release(*[f for f, t in jobs.started if t != "chrome"])   # the Firefox tabs free up
    await until(lambda: len(jobs.started) == 5)
    assert {jobs.tab_of("d.png"), jobs.tab_of("e.png")} <= {"fx1", "fx2"}
    jobs.release("d.png", "e.png")
    await asyncio.wait_for(pass_task, 2.0)
    assert all(i.status == ImageStatus.COMPLETED.value for i in images)


@pytest.mark.asyncio
async def test_unchecked_during_cooldown_the_tab_gets_nothing_when_the_timer_ends(jobs):
    """Chrome cooling (no job on it), unchecked, timer runs out while still pooled → no job for it."""
    bridge, pool, images = setup(["a.png", "b.png", "c.png"])
    page = pool.get_page("chrome")
    page.status, page.cooldown_until = PageStatus.COOLDOWN, 10**12   # cooling for a long time
    pass_task = start_pass(bridge, pool, images)
    await until(lambda: len(jobs.started) == 2)
    assert {t for _, t in jobs.started} == {"fx1", "fx2"}

    row(bridge, "chrome").enabled = False        # the reconcile has not removed it yet
    page.cooldown_until = 1.0                    # the timer ends → try_expire flips it STEADY
    live_bus(bridge).wake("page free")
    await asyncio.sleep(0.2)
    assert len(jobs.started) == 2, f"c.png went to the unchecked Chrome tab: {jobs.started}"

    jobs.release("a.png", "b.png")
    await until(lambda: len(jobs.started) == 3)
    assert jobs.tab_of("c.png") in {"fx1", "fx2"}
    jobs.release("c.png")
    await asyncio.wait_for(pass_task, 2.0)


@pytest.mark.asyncio
async def test_uncheck_while_idle_takes_the_tab_out_at_once(jobs):
    """Just unchecked from the worker list (idle, no job): the pool drops it and no job reaches it."""
    bridge, pool, images = setup(["a.png", "b.png"])
    uncheck(bridge, "chrome")
    assert pool.get_page("chrome") is None
    pass_task = start_pass(bridge, pool, images)
    await until(lambda: len(jobs.started) == 2)
    assert {t for _, t in jobs.started} == {"fx1", "fx2"}
    jobs.release("a.png", "b.png")
    await asyncio.wait_for(pass_task, 2.0)


@pytest.mark.asyncio
async def test_a_job_already_waiting_for_a_page_rereads_the_checkbox(jobs):
    """d waits (all three busy) when Chrome is unchecked; Chrome frees first — d must keep waiting."""
    bridge, pool, images = setup(["a.png", "b.png", "c.png", "d.png"])
    pass_task = start_pass(bridge, pool, images)
    await until(lambda: len(jobs.started) == 3)
    await asyncio.sleep(0.1)                     # d is inside the free-page wait now
    chrome_job = next(f for f, t in jobs.started if t == "chrome")
    row(bridge, "chrome").enabled = False        # no membership pass: the gate alone must hold
    jobs.release(chrome_job)
    await asyncio.sleep(0.2)
    assert jobs.tab_of("d.png") == "", f"d went to the unchecked Chrome tab: {jobs.started}"

    fx_job = next(f for f, t in jobs.started if t == "fx1")
    jobs.release(fx_job)
    await until(lambda: jobs.tab_of("d.png") != "")
    assert jobs.tab_of("d.png") == "fx1"
    jobs.release(*[f for f, _ in jobs.started])
    await asyncio.wait_for(pass_task, 2.0)


@pytest.mark.asyncio
async def test_a_removed_row_stops_its_tab_too(jobs):
    """✕ rebuilds `state.urls` (new list): the tab of the gone row takes no job either."""
    bridge, pool, images = setup(["a.png", "b.png", "c.png", "d.png"])
    pass_task = start_pass(bridge, pool, images)
    await until(lambda: len(jobs.started) == 3)
    bridge.state.urls = [u for u in bridge.state.urls if u.tab_id != "chrome"]
    jobs.release(next(f for f, t in jobs.started if t == "chrome"))
    await asyncio.sleep(0.2)
    assert jobs.tab_of("d.png") == ""
    jobs.release(*[f for f, _ in jobs.started])
    await until(lambda: jobs.tab_of("d.png") != "")
    assert jobs.tab_of("d.png") in {"fx1", "fx2"}
    jobs.release("d.png")
    await asyncio.wait_for(pass_task, 2.0)


@pytest.mark.asyncio
async def test_a_row_checked_mid_pass_takes_work_at_once(jobs):
    """The live read works both ways: a re-checked idle tab picks up the waiting image."""
    bridge, pool, images = setup(["a.png", "b.png", "c.png"])
    row(bridge, "chrome").enabled = False
    pass_task = start_pass(bridge, pool, images)
    await until(lambda: len(jobs.started) == 2)
    await asyncio.sleep(0.1)
    assert jobs.tab_of("c.png") == ""
    row(bridge, "chrome").enabled = True
    live_bus(bridge).wake("urls")
    await until(lambda: jobs.tab_of("c.png") != "")
    assert jobs.tab_of("c.png") == "chrome"
    jobs.release("a.png", "b.png", "c.png")
    await asyncio.wait_for(pass_task, 2.0)


def test_live_allowed_reads_the_rows_as_they_are_now():
    bridge = SimpleNamespace(state=SimpleNamespace(urls=make_urls(["t1", "t2"])))
    assert ac.live_allowed(bridge) == {"t1", "t2"}
    bridge.state.urls[0].enabled = False
    assert ac.live_allowed(bridge) == {"t2"}
    bridge.state.urls = []
    assert ac.live_allowed(bridge) == set()
    assert ac.live_allowed(SimpleNamespace()) == set()


# ---- the sequential lane: claim → cooldown wait → the tab must still be checked ----

def _seq_ctx(tabs=("tab1", "tab2")):
    from app.browser.page_status import PageInfo
    from app.browser.page_pool import PagePool
    from app.services import batch_orchestrator as bo
    from tests.test_batch_orchestrator import make_bridge, make_ctx
    pool = PagePool()
    for t in tabs:
        pool.add_page(PageInfo(ws_url=f"ws://{t}", tab_id=t, url="https://arena.ai", is_connected=True))
    bridge = make_bridge(urls=make_urls(list(tabs)), pool=pool)
    return bo, pool, make_ctx(bridge, tab_id="tab1")


@pytest.mark.asyncio
async def test_sequential_lane_moves_off_a_tab_unchecked_during_its_cooldown_wait(monkeypatch):
    bo, pool, ctx = _seq_ctx()
    waited = []

    async def wait_and_uncheck(pool_, tab_id, bridge):
        waited.append(tab_id)
        if tab_id == "tab1":
            row(bridge, "tab1").enabled = False   # the user unchecks it while it cools
        return True

    monkeypatch.setattr(bo, "wait_for_tab_ready", wait_and_uncheck)
    assert await bo._claim_ready_tab(ctx) is True
    assert ctx.tab_id == "tab2" and waited == ["tab1", "tab2"]
    assert any("unchecked during its cooldown" in m for m, _ in ctx.bridge._logs)


@pytest.mark.asyncio
async def test_sequential_lane_stops_when_no_checked_tab_is_left(monkeypatch):
    bo, pool, ctx = _seq_ctx(tabs=("tab1",))

    async def wait_and_uncheck(pool_, tab_id, bridge):
        row(bridge, tab_id).enabled = False
        return True

    monkeypatch.setattr(bo, "wait_for_tab_ready", wait_and_uncheck)
    assert await bo._claim_ready_tab(ctx) is False   # never runs the job on the unchecked tab
    assert any("No usable checked tab left" in m for m, _ in ctx.bridge._logs)


@pytest.mark.asyncio
async def test_sequential_lane_gives_up_when_the_checked_tabs_keep_changing(monkeypatch):
    bo, pool, ctx = _seq_ctx()

    async def flip(pool_, tab_id, bridge):   # whatever is claimed gets unchecked, the other re-checked
        for u in bridge.state.urls:
            u.enabled = u.tab_id != tab_id
        return True

    monkeypatch.setattr(bo, "wait_for_tab_ready", flip)
    assert await bo._claim_ready_tab(ctx) is False
    assert any("kept changing" in m for m, _ in ctx.bridge._logs)


# ---- end to end: the real Bridge, the real URL-list checkbox slot ----

@pytest.mark.asyncio
async def test_the_real_toggle_url_slot_stops_the_chrome_tab_mid_pass(tmp_path, jobs):
    """The user's click, unabridged: `Bridge.toggle_url` (commit → membership gate, receivers,
    save, undo) while Chrome's job runs; the next jobs go to the two Firefox-style tabs."""
    import json
    from tests.characterization.harness import CORE_STACK, build_bridge, build_stack
    pool = make_pool(list(TABS))
    for tab in TABS:
        pool.register_client(tab, object(), object())
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=5, tab_ids=list(TABS), pool=pool)
    bridge, images = env.bridge, list(env.bridge.state.images)
    pass_task = start_pass(bridge, pool, images)
    await until(lambda: len(jobs.started) == 3)
    chrome_job = next(f for f, t in jobs.started if t == "chrome")

    reply = json.loads(bridge.toggle_url(row(bridge, "chrome").id))   # the URL List checkbox
    assert reply == {"ok": True, "enabled": False}
    jobs.release(chrome_job)
    await asyncio.sleep(0.2)
    assert len(jobs.started) == 3, f"a job went to the unchecked Chrome tab: {jobs.started}"

    jobs.release(*[f for f, t in jobs.started if t != "chrome"])
    await until(lambda: len(jobs.started) == 5)
    assert all(t != "chrome" for f, t in jobs.started if f != chrome_job)
    jobs.release(*[f for f, _ in jobs.started])
    await asyncio.wait_for(pass_task, 2.0)
    assert all(i.status == ImageStatus.COMPLETED.value for i in images)
