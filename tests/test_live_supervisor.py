"""S5 — the always-live run loop (D-8 one writer, I-41/S8 live supervisor).

`run_live` replaces "one batch then idle": waits on the S4 bus while the queue
/ tab / connection state asks for waiting, re-picks work without a restart, and
ends only on cancel/stop-after. RULE 8: the real `run_live` coroutine on a real
asyncio task with a real LiveBus; passes that would need the whole CDP lane are
pinned by the characterization goldens driven through the supervisor runner
(`tests/characterization/test_batch_goldens.py`, byte-identical).
"""

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

import app.services.batch_orchestrator as bo
import app.services.multi_page_dispatcher as mpd
from app.core.models import UrlRow
from app.services.live import feed
from app.services.live.bus import LiveBus, live_bus
from app.services.run_state import schedule_batch
from tests.test_multi_page_dispatcher_run import make_img
from tests.test_panel_slots import make_cdp, make_host, make_state

import app.services.live.supervisor as sup                   # RED: module missing


def host_with(images, urls=None, pool=None, results=None):
    logs = []
    emitted = []
    b = SimpleNamespace(
        state=make_state(images=images, urls=urls or []),
        cdp=make_cdp(connected=True),
        _page_pool=pool,
        _live_bus=LiveBus(),
        _cancel_requested=False, _pause_requested=False, _stop_after=False,
        _run_state="idle", _live_supervisor=False,
        _log=lambda msg, level="info": logs.append((level, msg)),
        _emit_arena_state=lambda: emitted.append("arena"),
        _emit_pool_status=lambda: emitted.append("pool"),
    )
    b.state.recalculate_progress = lambda: None
    b.state.run_state = "idle"                      # the persisted field (L-2)
    b._save_arena = lambda: emitted.append("save")
    return b, logs, emitted


async def wait_until(fn, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if fn():
            return
        await asyncio.sleep(0.01)
    assert False, "condition never became true"


@pytest.mark.asyncio
async def test_no_work_waits_and_never_ends(monkeypatch):
    monkeypatch.setattr(sup, "WAIT_SEC", 0.02)
    bridge, logs, _ = host_with(images=[])
    sup.set_run_state(bridge, "running")
    task = asyncio.create_task(sup.run_live(bridge))

    await asyncio.sleep(0.09)                       # a few wait cycles
    assert not task.done(), "no work must never end the run"
    assert bridge._live_supervisor is True
    assert bridge._run_state == "running"
    hits = [m for _l, m in logs if "0 queued images" in m]
    assert len(hits) == 1, "the idle line is throttled, not spammed"

    bridge._stop_after = True                       # the one stop lever
    live_bus(bridge).wake("stop")
    await asyncio.wait_for(task, 2)
    assert bridge._run_state == "idle" and bridge._live_supervisor is False


@pytest.mark.asyncio
async def test_new_work_is_picked_up_without_a_restart(monkeypatch):
    monkeypatch.setattr(sup, "WAIT_SEC", 0.02)
    bridge, logs, _ = host_with(images=[])
    sup.set_run_state(bridge, "running")
    task = asyncio.create_task(sup.run_live(bridge))
    await asyncio.sleep(0.06)
    assert any("0 queued" in m for _l, m in logs)

    img = make_img("late.png")                      # arrives while live
    bridge.state.images.append(img)
    feed.commit_queue(bridge, "reset_all")
    await wait_until(lambda: any("no usable checked tab" in m for _l, m in logs))
    assert not task.done()
    assert sup.plan_pass(bridge).reason == "no_tab"            # re-plan saw the new work

    bridge._stop_after = True
    live_bus(bridge).wake("stop")
    await asyncio.wait_for(task, 2)


def real_cooling_pool():
    from app.browser.page_pool import PagePool
    from app.browser.page_status import PageInfo, PageStatus

    pool = PagePool()
    page = PageInfo(ws_url="ws://x", tab_id="t1", is_connected=True)
    pool.add_page(page)                              # add promotes to STEADY…
    page.status = PageStatus.COOLDOWN                # …model the timed cooling here
    page.cooldown_until = 9e18
    return pool


@pytest.mark.parametrize("reason", ["no_images", "cdp_down", "no_tab", "all_cooling"])
def test_plan_pass_names_the_wait_reason(reason):
    images = [] if reason == "no_images" else [make_img("a.png")]
    urls = ([UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")]
            if reason == "all_cooling" else [])
    bridge, _logs, _e = host_with(images=images, urls=urls)
    if reason == "cdp_down":
        bridge.cdp = make_cdp(connected=False)
    if reason == "all_cooling":
        bridge._page_pool = real_cooling_pool()
    assert sup.plan_pass(bridge).reason == reason


def test_work_available_plans_an_empty_reason():
    bridge, _logs, _e = host_with(
        images=[make_img("work.png")],
        urls=[UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")])
    plan = sup.plan_pass(bridge)
    assert plan.reason == "" and len(plan.images) == 1 and plan.allowed == {"t1"}
    assert sup.REASON_LINES.get(plan.reason) is None, "no wait line for a working pass"


@pytest.mark.asyncio
async def test_cancel_is_the_way_out_and_ends_in_idle(monkeypatch):
    monkeypatch.setattr(sup, "WAIT_SEC", 60.0)      # the cancel must pierce the wait
    bridge, logs, emitted = host_with(images=[])
    sup.set_run_state(bridge, "running")
    task = asyncio.create_task(sup.run_live(bridge))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):     # never swallowed
        await task
    assert any("🏁 Batch cancelled" in m for _l, m in logs)
    assert bridge._run_state == "idle" and bridge._live_supervisor is False
    assert bridge.state.run_state == "idle"          # L-2: persisted field follows (D-8)


@pytest.mark.asyncio
async def test_stop_after_before_the_loop_ends_immediately(monkeypatch):
    monkeypatch.setattr(sup, "WAIT_SEC", 60.0)
    bridge, logs, _ = host_with(images=[])
    bridge._stop_after = True
    sup.set_run_state(bridge, "running")
    await asyncio.wait_for(sup.run_live(bridge), 1.5)   # returns at once, no wait
    assert bridge._run_state == "idle"
    assert [m for _l, m in logs if "queued images" in m] == []   # no wait chatter


def test_run_state_has_exactly_one_writer():
    """D-8/L-2 lock: no `_run_state =` outside supervisor + slots' delegates."""
    for mod in (bo, mpd):
        src = inspect.getsource(mod)
        assert "_run_state =" not in src, f"{mod.__name__} must not write run state"
    assert "bridge._run_state = value" in inspect.getsource(sup.set_run_state)
    b, _l, _e = host_with(images=[])
    sup.set_run_state(b, "paused")
    assert b._run_state == "paused" and b.state.run_state == "paused"


def test_start_while_live_wakes_instead_of_refusing(monkeypatch):
    from app.ui.panels import run_control as rc
    from app.ui.panels.run_control import RunControlMixin

    img = make_img("queued.png")
    host, logs = make_host(
        (RunControlMixin,),
        state=make_state(images=[img], urls=[UrlRow.create("https://arena.ai/c", enabled=True, tab_id="t1")]),
        config=None, cdp=make_cdp(connected=True),
        _cancel_requested=False, _pause_requested=False, _stop_after=False,
        _run_state="running", _batch_future=object(), _live_supervisor=True,
        _page_pool=None)
    assert json.loads(host.start_run())["ok"] is True
    assert any("Run already live — queue re-checked" in m for _l, m in logs)
    assert live_bus(host).reasons() == ["start"]
    assert not any("Already running" in m for _l, m in logs)


def test_folder_ai_refused_only_while_an_image_processes(monkeypatch):
    from app.ui.panels import queue_scan as qs
    from app.ui.panels.queue_scan import QueueScanMixin

    def make(images, state="running"):
        st = make_state(images=images)
        st.folder = {"root_path": "/tmp"}
        bridge = SimpleNamespace(
            _run_state=state, _scan_in_progress=False, state=st,
            _log=lambda *a: None)
        return bridge

    monkeypatch.setattr(qs.folder_ai_service, "submit_folder_ai", lambda *a, **k: None)
    idle_img = make_img("done.png"); idle_img.status = "completed"
    res = json.loads(qs.run_folder_ai_request(make([idle_img], state="running"), "drop"))
    assert res.get("ok") is True, "live-but-idle queue: folder op allowed now"
    busy_img = make_img("work.png"); busy_img.status = "processing"
    res = json.loads(qs.run_folder_ai_request(make([busy_img], state="running"), "drop"))
    assert res == {"ok": False, "error": "stop the run first"}
