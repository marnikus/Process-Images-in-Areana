"""Planning gates become pool-aware (2026-09-25, design D4).

* `cdp down` waits only while NO checked page is free — a free Firefox page
  means there is work to hand out with Chrome disconnected;
* a wanted Firefox primary is claimed IN PLACE (no ws_url ⇒ no CDP move);
* the parallel feeder is entered whenever a checked page is Firefox — the
  feeder's bounded wait is the right semantics for a single busy macro tab,
  and the sequential (primary-CDP) lane never receives a Firefox page.

RED at base: `plan_pass` says "cdp down" with a free Firefox worker, and
`_move_to_tab` reports a reconnect failure for a tab that has no socket.
"""

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.browser.uivision import pool_tabs as pt
from app.services import batch_orchestrator as bo
from app.services.live import supervisor as sv
from app.core.models import UrlRow
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit

FF = "9THrgpBc.Profile1_tab1"


def env_with_firefox(tmp_path, *, free=True, n_images=1):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=n_images, tab_ids=[])
    pool = PagePool(logger=lambda m, l="info": None)
    tab = pt.FirefoxTab(id=FF, url="https://arena.ai/c/7", title="A",
                        profile="P1", profile_dir="/x/P1", ws_url=f"firefox://{FF}")
    pool.add_page(pt.page_for(tab))
    if not free:
        pool.mark_busy(FF, "other-job")
    env.bridge._page_pool = pool
    env.bridge.state.urls = [UrlRow.create("https://arena.ai/c/7", enabled=True, tab_id=FF)]
    env.bridge.cdp.is_connected = False   # Chrome down (FakeCDP default may vary)
    return env


@pytest.mark.asyncio
async def test_plan_pass_runs_with_a_free_firefox_page_while_cdp_is_down(tmp_path):
    env = env_with_firefox(tmp_path, free=True)
    plan = await sv.plan_pass(env.bridge)
    assert plan.reason == ""
    assert plan.tab_id == FF
    assert plan.allowed == {FF}


@pytest.mark.asyncio
async def test_cdp_down_still_waits_when_no_checked_page_is_free(tmp_path):
    env = env_with_firefox(tmp_path, free=False)
    plan = await sv.plan_pass(env.bridge)
    assert plan.reason == "cdp down"


@pytest.mark.asyncio
async def test_allowed_free_without_any_pages_stays_cdp_down(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge._page_pool = PagePool(logger=lambda m, l="info": None)
    env.bridge.state.urls = [UrlRow.create("https://x", enabled=True, tab_id="c1")]
    env.bridge.cdp.is_connected = False
    plan = await sv.plan_pass(env.bridge)
    assert plan.reason == "cdp down"


@pytest.mark.asyncio
async def test_move_to_tab_claims_a_firefox_primary_in_place(tmp_path, monkeypatch):
    env = env_with_firefox(tmp_path)
    connects = []

    async def no_connect(ws):
        connects.append(ws)
        return True

    env.bridge.cdp.connect = no_connect
    got = await bo._move_to_tab(env.bridge, "", FF)
    assert got == FF
    assert connects == []          # no socket to move to — claimed in place


def test_parallel_lane_opens_for_a_single_firefox_page(tmp_path, monkeypatch):
    env = env_with_firefox(tmp_path)
    dispatched = []

    async def spy_dispatch(bridge, pool, images, urls):
        dispatched.append(len(images))

    monkeypatch.setattr(bo, "dispatch_parallel", spy_dispatch)
    ctx = bo.BatchCtx(bridge=env.bridge, ctrl=None, allowed={FF},
                      images=[object()])
    assert asyncio_run(bo._try_parallel(ctx)) is True
    assert dispatched == [1]


def test_single_chrome_page_keeps_the_sequential_lane(tmp_path, monkeypatch):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=["c1"])
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(ws_url="ws://c1", tab_id="c1", url="https://arena.ai",
                           title="T", is_connected=True, browser="chrome"))
    env.bridge._page_pool = pool
    env.bridge.state.urls = [UrlRow.create("https://arena.ai", enabled=True, tab_id="c1")]
    dispatched = []

    async def spy_dispatch(bridge, pool, images, urls):
        dispatched.append(1)

    monkeypatch.setattr(bo, "dispatch_parallel", spy_dispatch)
    ctx = bo.BatchCtx(bridge=env.bridge, ctrl=None, allowed={"c1"}, images=[object()])
    assert asyncio_run(bo._try_parallel(ctx)) is False
    assert dispatched == []


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


def test_has_firefox_without_a_pool_is_false(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge._page_pool = None
    ctx = bo.BatchCtx(bridge=env.bridge, ctrl=None, allowed={FF}, images=[object()])
    assert bo._has_firefox(ctx) is False


def test_has_firefox_survives_a_pool_without_a_pages_map(tmp_path):
    from types import SimpleNamespace as NS
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge._page_pool = NS(_pages=None)   # .values() raises → AttributeError → False
    ctx = bo.BatchCtx(bridge=env.bridge, ctrl=None, allowed={FF}, images=[object()])
    assert bo._has_firefox(ctx) is False
