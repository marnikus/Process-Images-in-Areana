"""I-64 · A Firefox worker needs no CDP socket — the run plans and dispatches it.

"cdp down" only blocks when no checked Firefox page exists; the primary-tab
pick returns a Firefox tab as is (no socket move); any batch with a Firefox
page goes through the feeder (its lanes are per page), even with one page.
"""

from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo
from app.core.models import UrlRow
from app.services import batch_orchestrator as bo
from app.services.live import supervisor as sv
from tests.test_batch_orchestrator import make_bridge, make_img

pytestmark = pytest.mark.unit

FOX = "9THrgpBc.Profile1_tab1"


def fox_pool():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id=FOX, title="LMArena", url="https://arena.ai/c/7", browser="firefox"))
    return pool


def disconnected(bridge):
    bridge.cdp = SimpleNamespace(is_connected=False, _current_tab_id="", connect=None)
    return bridge


def test_cdp_down_only_blocks_without_a_checked_firefox_page():
    bridge = disconnected(make_bridge(pool=fox_pool()))
    assert sv._cdp_down(bridge, {FOX}) is False
    assert sv._cdp_down(bridge, {"C1"}) is True
    bridge.cdp.is_connected = True
    assert sv._cdp_down(bridge, set()) is False


@pytest.mark.asyncio
async def test_a_firefox_only_pool_plans_a_pass_on_its_tab(monkeypatch):
    monkeypatch.setattr(sv, "queued_images", lambda bridge: [make_img()])
    bridge = disconnected(make_bridge(pool=fox_pool(), urls=[UrlRow.create("https://arena.ai/c/7", tab_id=FOX)]))
    plan = await sv.plan_pass(bridge)
    assert plan.reason == "" and plan.tab_id == FOX and plan.allowed == {FOX}


@pytest.mark.asyncio
async def test_the_primary_pick_returns_a_firefox_tab_without_a_socket_move():
    bridge = disconnected(make_bridge(pool=fox_pool()))
    assert await bo.resolve_and_claim_tab(bridge, "", {FOX}) == FOX


@pytest.mark.asyncio
async def test_one_firefox_page_is_enough_for_the_feeder(monkeypatch):
    seen = []

    async def fake_dispatch(bridge, pool, images, urls):
        seen.append([getattr(i, "id", i) for i in images])
    monkeypatch.setattr(bo, "dispatch_parallel", fake_dispatch)
    bridge = disconnected(make_bridge(pool=fox_pool()))
    ctx = bo.BatchCtx(bridge=bridge, ctrl=None, urls=[], allowed={FOX}, tab_id=FOX, images=[make_img()])
    assert await bo._try_parallel(ctx) is True and seen == [["pic1.png"]]


@pytest.mark.asyncio
async def test_a_firefox_only_batch_never_probes_a_cdp_page(monkeypatch):
    probed = []

    async def fake_warn(bridge, ctrl):
        probed.append(ctrl)
    monkeypatch.setattr(bo, "_warn_unready", fake_warn)
    bridge = disconnected(make_bridge(pool=fox_pool()))
    plan = SimpleNamespace(urls=[], allowed={FOX}, tab_id=FOX, images=[make_img()])
    ctx = await bo.prepare_batch(bridge, plan)
    assert ctx.tab_id == FOX and probed == []
    bridge.cdp.is_connected = True
    await bo.prepare_batch(bridge, plan)
    assert len(probed) == 1
