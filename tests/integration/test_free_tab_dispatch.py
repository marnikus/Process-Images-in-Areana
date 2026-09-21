"""The run must use a free `steady (ready)` worker instead of parking on `no usable tab`.

The bug (2026-09-21): a pool holding one busy worker (`waiting_generation`,
mid-job) and one `steady (ready)` worker, both owned by checked URL rows, with
images pending — and the live loop sat on the `no tab` wait state, badge
`RUN CYCLE ON · no usable tab`, while the ready worker idled.

`plan_pass` gated the whole pass on resolving a **primary CDP tab**
(`resolve_and_claim_tab`), which answers `''` whenever the single connection
cannot be pointed at the ready worker — its pooled page carries no socket, or
the reconnect fails, while `cdp._current_tab_id` is empty. But the lane that
would actually run the work — the parallel feeder — never touches the primary
connection: it claims a pooled page and uses that page's own client. So the
gate refused a pass the dispatcher was ready to run.

RED at base: `plan.reason == 'no tab'` and no job is ever started, although
`pool` reports a free checked worker.
"""

import asyncio

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.enums import ImageStatus
from app.services import multi_page_dispatcher as mpd
from app.services.live import supervisor as sv
from tests.characterization.fakes import FakeCDP, install_patches
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

BUSY, READY = "marnikus_0002", "morismasolen_0003"


class UnreachableCDP(FakeCDP):
    """The primary connection cannot be pointed at any pooled tab.

    `_current_tab_id` is empty (nothing attached) and every `connect` fails —
    the state that made `resolve_and_claim_tab` answer `''`.
    """

    def __init__(self):
        super().__init__(tab_id="")

    async def connect(self, ws_url: str) -> bool:
        return False


def mixed_pool() -> PagePool:
    """One worker mid-generation, one `steady (ready)` with no live timer."""
    pool = PagePool(logger=lambda m, lvl="info": None)
    for tab in (BUSY, READY):
        pool.add_page(PageInfo(tab_id=tab, ws_url=f"ws://{tab}", title=f"T-{tab}",
                               url=f"https://arena.ai/{tab}", is_connected=True))
        pool.register_client(tab, object(), object())
    busy = pool.get_page(BUSY)
    busy.status, busy.current_image = PageStatus.WAITING_GENERATION, "icon-lightbulb-gear.png"
    return pool


@pytest.fixture
def ran(monkeypatch):
    """Record `(tab_id, filename)` per job; the block stack itself is out of scope."""
    calls: list = []

    async def fake_baseline(_ctrl):
        return {"outputs": []}

    async def fake_run(job_ctx):
        calls.append((job_ctx.tab_id, job_ctx.img.filename))
        return False, "", None, None

    async def fake_finish(ctx):
        ctx.pool.mark_steady(ctx.tab_id)

    monkeypatch.setattr(mpd, "capture_baseline", fake_baseline)
    monkeypatch.setattr(mpd, "run_blocks_for_image", fake_run)
    monkeypatch.setattr(mpd, "finish_page_after_job", fake_finish)
    return calls


def live_env(tmp_path, monkeypatch, pool, n_images=6):
    """Golden-harness bridge on the mixed pool, both workers owned by checked rows."""
    install_patches(monkeypatch)
    return build_bridge(tmp_path, build_stack(CORE_STACK), n_images=n_images,
                        tab_ids=[BUSY, READY], pool=pool, cdp=UnreachableCDP())


async def test_a_pass_is_planned_while_a_checked_worker_is_free(tmp_path, monkeypatch):
    """The gate must reflect what the pass can do, not whether the primary tab resolved."""
    pool = mixed_pool()
    env = live_env(tmp_path, monkeypatch, pool)
    plan = await sv.plan_pass(env.bridge)
    assert len(plan.images) == 6 and plan.allowed == {BUSY, READY}
    assert pool.status_snapshot()["free"] == 1, "the ready worker is free — the premise of the bug"
    assert plan.reason == "", f"a free checked worker must not read as {plan.reason!r}"


async def test_the_pending_image_runs_on_the_free_worker_not_the_busy_one(tmp_path, monkeypatch, ran):
    """End of the chain: the pass reaches the dispatcher and the ready worker takes the job."""
    pool = mixed_pool()
    env = live_env(tmp_path, monkeypatch, pool, n_images=1)
    plan = await sv.plan_pass(env.bridge)
    await asyncio.wait_for(sv.run_pass(env.bridge, plan), 5)
    assert [tab for tab, _img in ran] == [READY], "the free worker must receive the job"
    assert env.bridge.state.images[0].status == ImageStatus.COMPLETED.value
    assert pool.get_page(BUSY).current_image == "icon-lightbulb-gear.png", "the busy worker keeps its job"


async def test_a_broken_pool_read_stays_a_loud_wait_state(tmp_path, monkeypatch):
    """RULE 4: a pool that cannot be counted is broken, not free — the run waits, it never guesses."""
    pool = mixed_pool()

    class BrokenLock:
        def __enter__(self):
            raise RuntimeError("pool lock unavailable")

        def __exit__(self, *exc):
            return False

    def boom():
        raise RuntimeError("pool snapshot unavailable")

    env = live_env(tmp_path, monkeypatch, pool)
    monkeypatch.setattr(pool, "status_snapshot", boom)
    monkeypatch.setattr(pool, "_lock", BrokenLock())
    plan = await sv.plan_pass(env.bridge)
    assert plan.reason == "no tab"


async def test_a_single_pooled_worker_still_needs_the_primary_tab(tmp_path, monkeypatch):
    """RULE 4: the sequential lane really does need the primary connection — still a loud wait state."""
    pool = PagePool(logger=lambda m, lvl="info": None)
    pool.add_page(PageInfo(tab_id=READY, ws_url=f"ws://{READY}", title="T",
                           url="https://arena.ai/x", is_connected=True))
    env = live_env(tmp_path, monkeypatch, pool)
    env.bridge.state.urls = env.bridge.state.urls[:1]
    env.bridge.state.urls[0].tab_id = READY
    plan = await sv.plan_pass(env.bridge)
    assert plan.reason == "no tab"
