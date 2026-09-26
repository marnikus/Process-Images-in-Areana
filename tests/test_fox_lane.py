"""I-64 · The Firefox job lane — one Ui.Vision macro per machine, an honest verdict.

The gate serializes every macro (pool jobs + the framework test) with the
user's delay between runs; the image is ALWAYS failed with a named reason
(owner decision 2026-09-25); the page is counted and cooled through the normal
finish (no CDP reset). Planner/runner are fakes behind `UiVisionDeps`; the pool,
the dispatcher and the finish path are real.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.enums import ImageStatus
from app.core.models import UrlRow
from app.services import multi_page_dispatcher as mpd
from app.services import uivision_job as uj
from app.services.cooldown_service import request_tab_abort, set_tab_image
from tests.test_multi_page_dispatcher_run import FakeBridge, make_img

pytestmark = pytest.mark.unit

FOX = "9THrgpBc.Profile1_tab2"


def fox_pool(*extra_chrome):
    pool = PagePool()
    pool.add_page(PageInfo(tab_id=FOX, title="LMArena", url="https://arena.ai/c/2",
                           browser="firefox", profile="Profile1"))
    for tab in extra_chrome:
        pool.add_page(PageInfo(tab_id=tab, ws_url=f"ws://{tab}", url="https://arena.ai/x", browser="chrome"))
    return pool


def lane_bridge(pool, plan=None, run=None, delay=0.0):
    bridge = FakeBridge()
    bridge._page_pool = pool
    bridge.config = SimpleNamespace(get_state=lambda key, default=None: {
        "cooldown_enabled": True, "cooldown_min_seconds": 120}.get(key, default))
    calls = SimpleNamespace(plans=[], runs=[])

    def fake_plan(tab_id):
        calls.plans.append(tab_id)
        return plan if plan is not None else SimpleNamespace(tab_id=tab_id)

    async def fake_run(job, report, stop):
        calls.runs.append(job)
        report("launch", "launched (pid 7)")
        return run or SimpleNamespace(kind="ok", message="macro completed")

    bridge._uivision_deps = uj.UiVisionDeps(plan=fake_plan, run=fake_run, delay_sec=lambda: delay)
    return bridge, calls


def clock():
    now = [100.0]

    async def sleep(sec):
        now[0] += sec
    return now, sleep


@pytest.mark.asyncio
async def test_the_gate_runs_one_macro_and_waits_the_users_delay():
    now, sleep = clock()
    gate = uj.UiVisionGate(clock=lambda: now[0], sleep=sleep)
    assert await gate.acquire(lambda: False) and gate.busy
    gate.release(3)
    assert gate.busy                                     # the delay after a run is still busy
    assert await gate.acquire(lambda: False)
    assert now[0] >= 103.0
    gate.release(0)
    assert not gate.busy


@pytest.mark.asyncio
async def test_stop_ends_the_wait_and_holds_nothing():
    now, sleep = clock()
    gate = uj.UiVisionGate(clock=lambda: now[0], sleep=sleep)
    await gate.acquire(lambda: False)                    # another macro holds the machine
    assert await gate.acquire(lambda: True) is False
    gate.release(None)
    assert not gate.busy
    bridge = SimpleNamespace()
    assert uj.uivision_gate(bridge) is uj.uivision_gate(bridge)   # one gate per bridge


def test_every_verdict_names_its_reason():
    ok = uj.verdict_error(SimpleNamespace(kind="ok", message="macro completed"))
    assert ok == uj.OK_NO_OUTPUT and "not implemented yet" in ok
    assert uj.verdict_error(SimpleNamespace(kind="error", message="E212: tab")) == "Firefox macro error: E212: tab"
    assert uj.verdict_error(SimpleNamespace(kind="timeout", message="no status")).startswith("Firefox macro timeout:")
    assert uj.verdict_error(SimpleNamespace(kind="stopped", message="x")).startswith("Cancelled")
    assert uj.verdict_error(object()).startswith("Firefox macro error:")


def test_a_uivision_page_is_known_by_its_browser_or_its_key():
    pool = fox_pool("C1")
    assert uj.is_uivision_page(pool, FOX) and not uj.is_uivision_page(pool, "C1")
    assert not uj.is_uivision_page(pool, "missing") and not uj.is_uivision_page(None, FOX)
    assert uj.has_uivision_page(pool, {"C1", FOX}) and not uj.has_uivision_page(pool, {"C1"})
    assert not uj.has_uivision_page(pool, None)


@pytest.mark.asyncio
async def test_a_job_plans_runs_and_answers_failed_with_the_ok_reason():
    bridge, calls = lane_bridge(fox_pool())
    assert await uj.run_uivision_job(bridge, FOX) == (True, uj.OK_NO_OUTPUT)
    assert calls.plans == [FOX] and len(calls.runs) == 1
    assert any("🦊" in m and "launch: launched" in m for _lvl, m in bridge.logs)
    assert not uj.uivision_gate(bridge).busy            # released (delay 0)


@pytest.mark.asyncio
async def test_a_refused_plan_never_launches_and_names_why():
    bridge, calls = lane_bridge(fox_pool(), plan="the tab is gone")
    assert await uj.run_uivision_job(bridge, FOX) == (True, "Firefox job not run — the tab is gone")
    assert calls.runs == [] and any(lvl == "error" for lvl, _m in bridge.logs)


@pytest.mark.asyncio
async def test_no_deps_is_a_named_failure():
    bridge = FakeBridge()
    bridge._page_pool = fox_pool()
    failed, err = await uj.run_uivision_job(bridge, FOX)
    assert failed and "not wired" in err


@pytest.mark.asyncio
async def test_a_second_job_waits_its_turn_and_a_tab_stop_ends_the_wait():
    bridge, calls = lane_bridge(fox_pool())
    set_tab_image(bridge._page_pool, FOX, "a.png")      # the dispatcher records the image first
    gate = uj.uivision_gate(bridge)
    await gate.acquire(lambda: False)                   # the framework test holds the machine
    waiting = asyncio.ensure_future(uj.run_uivision_job(bridge, FOX))
    await asyncio.sleep(0.05)
    assert not waiting.done() and any("waiting for the Ui.Vision slot" in m for _l, m in bridge.logs)
    assert request_tab_abort(bridge._page_pool, FOX)    # the row's Stop button
    assert await asyncio.wait_for(waiting, 2) == (True, "Cancelled while waiting for the Ui.Vision slot")
    assert calls.plans == []


@pytest.mark.asyncio
async def test_the_dispatcher_runs_a_firefox_page_through_the_lane_and_cools_it():
    pool = fox_pool()
    bridge, calls = lane_bridge(pool)
    img = make_img()
    urls = [UrlRow.create("https://arena.ai/c/2", enabled=True, tab_id=FOX)]
    await mpd.run_one_image_on_page(bridge, pool, img, urls)
    assert (img.status, img.error, img.attempt_count) == (ImageStatus.FAILED.value, uj.OK_NO_OUTPUT, 1)
    page = pool.get_page(FOX)
    assert page.jobs_completed == 1                      # counted like any finished job
    assert page.status == PageStatus.COOLDOWN and 100 < page.remaining_seconds() <= 120
    assert not any("reset failed" in m for _l, m in bridge.logs)   # no CDP chat to reset
    assert calls.plans == [FOX]
    assert bridge.job_finished.calls and '"failed"' in bridge.job_finished.calls[-1][1]
