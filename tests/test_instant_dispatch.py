"""Idle worker instant start (design B-1…B-4, 2026-09-21).

The bug: `dispatch_parallel` froze the pass's image list at planning time and
gathered one task per image, so an image that entered the queue *while* the
pass was open (a Reset, a Scan, a job finishing elsewhere) waited for the
whole pass — a ready tab idled next to a pending queue for as long as the
busy tab's captcha took. The dispatcher is now a feeder: it re-reads the one
eligibility rule each time a page is claimed and stops only when the queue is
empty and every task is done (or on Cancel / Stop-after).

RED at base: test 1 times out / B never starts while A is held.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.enums import ImageStatus
from app.services import multi_page_dispatcher as mpd
from app.services.live.bus import live_bus
from tests.test_multi_page_dispatcher_run import FakeBridge, make_img, make_pool, make_urls

pytestmark = pytest.mark.unit


def bridge_with(images):
    b = FakeBridge()
    b.state.images = list(images)
    b.state.settings = SimpleNamespace(retries={})
    return b


class Gate:
    """Holds the fake job open until `release()` — a captcha stand-in."""

    def __init__(self, *held):
        self.held = set(held)
        self.opened = asyncio.Event()
        self.started: list = []

    def make_run(self):
        async def run(job_ctx):
            self.started.append((job_ctx.img.filename, job_ctx.tab_id))
            if job_ctx.img.filename in self.held:
                await self.opened.wait()
            return False, "", None, None
        return run

    def release(self):
        self.opened.set()


@pytest.fixture
def seam(monkeypatch):
    gate = Gate()
    monkeypatch.setattr(mpd, "capture_baseline", _no_baseline)
    monkeypatch.setattr(mpd, "run_blocks_for_image", gate.make_run())

    async def finish(ctx):
        ctx.pool.mark_steady(ctx.tab_id)

    monkeypatch.setattr(mpd, "finish_page_after_job", finish)
    monkeypatch.setattr(mpd, "cooldown_aware_timeout", lambda pool: 2.0)
    return gate


async def _no_baseline(ctrl):
    return {"outputs": []}


def two_tab_pool():
    pool = make_pool(["t1", "t2"])
    for t in ("t1", "t2"):
        pool.register_client(t, object(), object())
    return pool


@pytest.mark.asyncio
async def test_an_image_queued_mid_pass_starts_on_the_idle_tab_at_once(seam):
    """The reported bug: A holds t1 (captcha); B is Reset into the queue afterwards; t2 must take B now."""
    seam.held.add("a.png")
    a, b = make_img("a.png", id="i1"), make_img("b.png", id="i2")
    b.selected = False  # not queued when the pass is planned
    bridge = bridge_with([a, b])
    pool = two_tab_pool()
    pass_task = asyncio.create_task(mpd.dispatch_parallel(bridge, pool, [a], make_urls(["t1", "t2"])))
    await asyncio.sleep(0.05)
    assert seam.started == [("a.png", "t1")] or seam.started == [("a.png", "t2")]

    b.selected = True  # "Reset" mid-pass → queued
    live_bus(bridge).wake("queue")
    await asyncio.wait_for(_until(lambda: len(seam.started) == 2), 1.0)
    assert {f for f, _ in seam.started} == {"a.png", "b.png"}
    assert len({t for _, t in seam.started}) == 2, "B went to the idle tab while A was still held"
    assert a.status == ImageStatus.PROCESSING.value  # A really was still running
    seam.release()
    await asyncio.wait_for(pass_task, 2.0)
    assert (a.status, b.status) == (ImageStatus.COMPLETED.value, ImageStatus.COMPLETED.value)


@pytest.mark.asyncio
async def test_a_tab_freeing_up_wakes_the_next_image_without_waiting_for_the_poll(seam, monkeypatch):
    """Ready ⇒ pickup on the bus wake: with the poll stretched to 5 s, B must still start within 0.3 s."""
    monkeypatch.setattr(mpd, "_WAIT_POLL_SEC", 5.0)
    monkeypatch.setattr(mpd, "cooldown_aware_timeout", lambda pool: 30.0)
    seam.held.add("a.png")
    a, b, c = make_img("a.png", id="i1"), make_img("b.png", id="i2"), make_img("c.png", id="i3")
    bridge = bridge_with([a, b, c])
    pool = two_tab_pool()
    pool.mark_busy("t2", "someone-else")  # only t1 can take work; the feeder must wait for it
    pass_task = asyncio.create_task(mpd.dispatch_parallel(bridge, pool, [a, b, c], make_urls(["t1", "t2"])))
    await asyncio.wait_for(_until(lambda: len(seam.started) == 1), 1.0)
    await asyncio.sleep(0.5)  # long enough for b to be waiting for a page (inside the 5 s poll)
    assert len(seam.started) == 1
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    seam.release()  # a finishes → t1 steady → (wake) → b starts, in order
    await asyncio.wait_for(_until(lambda: len(seam.started) >= 2), 1.0)
    assert loop.time() - t0 < 0.3, "the free-page wait rode the 5 s poll instead of the wake"
    assert seam.started[1][0] == "b.png", "queue order: b was next, not c"
    pool.mark_steady("t2")
    live_bus(bridge).wake("page free")
    await asyncio.wait_for(pass_task, 3.0)
    assert [f for f, _ in seam.started] == ["a.png", "b.png", "c.png"]


@pytest.mark.asyncio
async def test_the_feeder_never_sends_an_image_twice_and_honours_claim_denied(seam):
    a, b = make_img("a.png", id="i1"), make_img("b.png", id="i2")
    b.status = ImageStatus.COMPLETED.value  # in the seed list by mistake — claim-time rule refuses it (I-44)
    bridge = bridge_with([a, b])
    await asyncio.wait_for(mpd.dispatch_parallel(bridge, two_tab_pool(), [a, a, b], make_urls(["t1", "t2"])), 2.0)
    assert [f for f, _ in seam.started] == ["a.png"]
    assert any("Skipping b.png" in m for _, m in bridge.logs)


@pytest.mark.asyncio
async def test_cancel_and_stop_after_stop_the_feeder_without_a_new_task(seam):
    seam.held.add("a.png")
    a, b = make_img("a.png", id="i1"), make_img("b.png", id="i2")
    bridge = bridge_with([a, b])
    pool = make_pool(["t1"])
    pool.register_client("t1", object(), object())
    pass_task = asyncio.create_task(mpd.dispatch_parallel(bridge, pool, [a, b], make_urls(["t1"])))
    await asyncio.wait_for(_until(lambda: len(seam.started) == 1), 1.0)
    bridge._stop_after = True
    live_bus(bridge).wake("stop")
    seam.release()
    await asyncio.wait_for(pass_task, 2.0)
    assert [f for f, _ in seam.started] == ["a.png"]
    assert b.status != ImageStatus.PROCESSING.value
    assert any("Parallel batch complete" in m for _, m in bridge.logs)


@pytest.mark.asyncio
async def test_the_feeder_ends_when_the_queue_is_empty_and_all_tasks_are_done(seam):
    a = make_img("a.png", id="i1")
    bridge = bridge_with([a])
    await asyncio.wait_for(mpd.dispatch_parallel(bridge, two_tab_pool(), [a], make_urls(["t1", "t2"])), 2.0)
    assert a.status == ImageStatus.COMPLETED.value
    assert bridge.arena_emits >= 1


async def _until(pred, step=0.005):
    while not pred():
        await asyncio.sleep(step)


@pytest.mark.asyncio
async def test_a_single_image_on_a_two_tab_pool_goes_parallel_so_it_can_take_the_free_tab(monkeypatch):
    """B-3: one queued image must not queue behind a busy primary tab while another checked tab is idle."""
    from app.core.models import UrlRow
    from app.services import batch_orchestrator as bo
    from tests.test_batch_orchestrator import info, make_bridge, make_ctx, pool_with

    pool = pool_with(info("t1"), info("t2"))
    pool.mark_busy("t1", "someone-else")  # the primary is busy, t2 is idle
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="t1"),
            UrlRow.create("https://arena.ai/b", enabled=True, tab_id="t2")]
    one = make_img("only.png", id="i1")
    bridge = make_bridge(images=[one], urls=urls, pool=pool)
    sent = []

    async def fake_dispatch(bridge_, pool_, images, urls_):
        sent.extend(images)

    monkeypatch.setattr(bo, "dispatch_parallel", fake_dispatch)
    assert await bo._try_parallel(make_ctx(bridge, tab_id="t1", images=[one])) is True
    assert sent == [one]
    assert not any("only 1 page" in m for m, _ in bridge._logs)


@pytest.mark.asyncio
async def test_a_free_page_wait_that_times_out_while_feeding_logs_and_moves_on(seam, monkeypatch):
    """The bounded wait (RULE 7) still ends: no page came in time → one ⏰ line, the image is left queued, the pass ends."""
    monkeypatch.setattr(mpd, "cooldown_aware_timeout", lambda pool: 0.05)
    a = make_img("a.png", id="i1")
    bridge = bridge_with([a])
    pool = make_pool(["t1"], busy=("t1",))  # never frees
    pool.register_client("t1", object(), object())
    await asyncio.wait_for(mpd.dispatch_parallel(bridge, pool, [a], make_urls(["t1"])), 2.0)
    assert seam.started == [] and a.status != ImageStatus.PROCESSING.value
    assert any("No free page for a.png" in m for _, m in bridge.logs)
