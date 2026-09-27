"""A job goes only to a tab whose URL row is checked NOW (I-69, 2026-09-27).

Owner: "Test if Job sending correct to the correct web page if url uncheck
during cooldown or just unchecked from worker list." The feeder took the
checked-tab set ONCE when the pass started (`ctx.allowed`) and a pass stays
open while the queue has work, so:

* a row unchecked while its job ran (pool exit deferred, RULE 15) got the
  next image the moment that job ended — before any reconcile pass removed it;
* a row unchecked while cooling, whose tab had not left the pool yet, got an
  image when the cooldown ended;
* a row checked mid-pass never got work until the next pass.

The claim now reads the live URL list (`bridge.state.urls`) on every attempt.
"""

import asyncio

import pytest

from app.services import auto_connect as ac
from app.services import cooldown_service as cs
from app.services import multi_page_dispatcher as mpd
from app.services.live.bus import live_bus
from tests.test_instant_dispatch import Gate, _no_baseline, _until, bridge_with, two_tab_pool
from tests.test_multi_page_dispatcher_run import fresh_chat, make_img, make_urls

pytestmark = pytest.mark.unit


@pytest.fixture
def seam(monkeypatch):
    gate = Gate()
    monkeypatch.setattr(mpd, "capture_baseline", _no_baseline)
    monkeypatch.setattr(mpd, "ensure_new_chat", fresh_chat)   # I-74 gate: part of the same seam
    monkeypatch.setattr(mpd, "run_blocks_for_image", gate.make_run())
    gate.finishes = []

    async def finish(ctx):  # cooldown off: the page is free the moment the job ends
        gate.finishes.append(ctx.tab_id)
        ctx.pool.mark_steady(ctx.tab_id)

    monkeypatch.setattr(mpd, "finish_page_after_job", finish)
    monkeypatch.setattr(mpd, "cooldown_aware_timeout", lambda pool: 2.0)
    return gate


def live_bridge(images, urls):
    bridge = bridge_with(images)
    bridge.state.urls = urls  # the one live URL list the checkboxes write
    return bridge


def row(urls, tab):
    return next(u for u in urls if u.tab_id == tab)


@pytest.mark.asyncio
async def test_a_row_unchecked_during_its_job_never_gets_the_next_image(seam):
    seam.held.update({"a.png", "c.png"})
    a, b, c = make_img("a.png", id="i1"), make_img("b.png", id="i2"), make_img("c.png", id="i3")
    urls = make_urls(["t1", "t2"])
    bridge, pool = live_bridge([a, b, c], urls), two_tab_pool()
    pool.mark_busy("t2", "someone-else")  # only t1 can start; b and c must wait
    task = asyncio.create_task(mpd.dispatch_parallel(bridge, pool, [a, b, c], list(urls)))
    await asyncio.wait_for(_until(lambda: seam.started == [("a.png", "t1")]), 1.0)

    row(urls, "t1").enabled = False  # unchecked mid-job: exit deferred, the page stays pooled
    pool.mark_steady("t2")           # t2 frees up
    live_bus(bridge).wake("page free")
    seam.release()                   # a ends → t1 free again
    await asyncio.wait_for(_until(lambda: len(seam.started) == 3), 1.5)
    await asyncio.wait_for(task, 2.0)
    assert [t for f, t in seam.started if f != "a.png"] == ["t2", "t2"], seam.started


@pytest.mark.asyncio
async def test_a_row_unchecked_while_cooling_is_skipped_when_the_cooldown_ends(seam):
    a = make_img("a.png", id="i1")
    urls = make_urls(["t1", "t2"])
    bridge, pool = live_bridge([a], urls), two_tab_pool()
    pool.mark_busy("t2", "someone-else")
    cs.start_cooldown(pool, "t1", 60, "job done")  # t1 cooling
    task = asyncio.create_task(mpd.dispatch_parallel(bridge, pool, [a], list(urls)))
    await asyncio.sleep(0.05)
    row(urls, "t1").enabled = False  # unchecked during the cooldown
    cs.reset_cooldown(pool, "t1")    # cooldown over (page still pooled — no pass yet)
    live_bus(bridge).wake("page free")
    await asyncio.sleep(0.1)
    assert seam.started == [], "the unchecked tab took the image"
    pool.mark_steady("t2")
    live_bus(bridge).wake("page free")
    await asyncio.wait_for(task, 2.0)
    assert seam.started == [("a.png", "t2")]


@pytest.mark.asyncio
async def test_a_row_checked_mid_pass_gets_work_in_the_same_pass(seam):
    a = make_img("a.png", id="i1")
    urls = make_urls(["t1", "t2"])
    row(urls, "t2").enabled = False
    bridge, pool = live_bridge([a], urls), two_tab_pool()
    pool.mark_busy("t1", "someone-else")
    task = asyncio.create_task(mpd.dispatch_parallel(bridge, pool, [a], [row(urls, "t1")]))
    await asyncio.sleep(0.05)
    row(urls, "t2").enabled = True  # the user checks t2
    live_bus(bridge).wake("urls")
    await asyncio.wait_for(task, 2.0)
    assert seam.started == [("a.png", "t2")]
    assert a.assigned_url_id == row(urls, "t2").id, "the image records the row that owns its tab NOW"


def test_checked_tab_ids_now_reads_the_live_list_and_falls_back_only_without_one():
    from types import SimpleNamespace as NS
    urls = make_urls(["t1", "t2"])
    urls[0].enabled = False
    assert ac.checked_tab_ids_now(NS(state=NS(urls=urls)), {"t1"}) == {"t2"}
    assert ac.checked_tab_ids_now(NS(state=NS(urls=[])), {"t1"}) == set()   # empty list = nothing checked
    assert ac.checked_tab_ids_now(NS(state=NS()), {"t1"}) == {"t1"}           # no live list → pass snapshot
    assert ac.checked_tab_ids_now(None, None) == set()


@pytest.mark.asyncio
async def test_the_sequential_lane_leaves_a_tab_unchecked_since_the_plan():
    """One page at a time: the next image moves off a tab whose row was unchecked mid-pass."""
    from app.core.models import UrlRow
    from app.services import batch_orchestrator as bo
    from tests.test_batch_orchestrator import info, make_bridge, make_ctx, pool_with
    urls = [UrlRow.create("https://arena.ai/1", tab_id="tab1"), UrlRow.create("https://arena.ai/2", tab_id="tab2")]
    bridge = make_bridge(urls=urls, pool=pool_with(info("tab1"), info("tab2", ws="ws://two")))
    ctx = make_ctx(bridge, tab_id="tab1")          # planned with both rows checked
    urls[0].enabled = False                         # the user unchecks tab1
    assert await bo._claim_tab(ctx) is True
    assert ctx.tab_id == "tab2"
