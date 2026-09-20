"""S5 · the always-live run (`live/supervisor.run_live`, D-5 / D-8 / I-47).

A live run never ends by itself: no work / no tab / all cooling / CDP down
are **wait** states (throttled line + `bus.wait`), only Stop / Stop-after
end it, and `set_run_state` is the ONLY writer of `_run_state` (which also
makes the persisted `AppState.run_state` honest — L-2). Real `Bridge` from
the golden harness; the loop's poll is shortened, the throttle clock is fake.

RED at base: `ModuleNotFoundError: app.services.live.supervisor`.
"""

import asyncio
import json
import re
import time
from pathlib import Path

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services.live import supervisor as sv
from app.services.live.bus import LiveBus, live_bus
from app.ui.panels import queue_scan, run_control
from tests.characterization.fakes import FakeCDP, install_patches
from tests.characterization.harness import (CORE_STACK, RUNNERS, arm_hooks, build_bridge,
                                            build_stack, check_golden, collect_trace)

pytestmark = pytest.mark.unit
APP = Path(__file__).resolve().parents[1] / "app"


class FakeClock:
    def __init__(self, step=1.0):
        self.now, self.step = 1000.0, step

    def __call__(self):
        self.now += self.step
        return self.now


def live_env(tmp_path, monkeypatch, n_images=1, **kw):
    """Harness bridge whose loop polls fast, throttles on a fake clock and never really sleeps."""
    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=n_images, **kw)
    monkeypatch.setattr(sv, "WAIT_S", 0.005)
    real_sleep = asyncio.sleep

    async def yield_only(_s):
        await real_sleep(0)  # the pipeline's pacing sleeps become yields; the bus wait is a real timer
    monkeypatch.setattr(asyncio, "sleep", yield_only)
    env.bridge._live_bus = LiveBus(clock=FakeClock())
    env.patched, env.sleep = patched, real_sleep  # tests wait real time through `env.sleep`
    return env


def logs(env):
    return [m for m, _lvl in env.recs["arena_log"].calls]


def park_all(bridge):
    for img in bridge.state.images:
        img.status, img.selected = "completed", False


async def settle(task):
    try:
        await asyncio.wait_for(task, 5)
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_no_work_waits_and_never_ends(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch)
    park_all(env.bridge)
    task = asyncio.ensure_future(sv.run_live(env.bridge))
    await env.sleep(0.08)  # ≈ 16 polls, ≈ 16 s of fake clock — well inside one throttle window
    assert not task.done()
    assert env.bridge._run_state == "running" and env.bridge.state.run_state == "running"
    assert sum(m.startswith("🟢 Run live — 0 queued images") for m in logs(env)) == 1
    env.bridge._cancel_requested = True
    task.cancel()
    await settle(task)
    assert env.bridge._run_state == "idle"


@pytest.mark.asyncio
async def test_new_work_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch)
    park_all(env.bridge)
    task = asyncio.ensure_future(sv.run_live(env.bridge))
    await env.sleep(0.02)
    assert not task.done() and env.recs["job_started"].calls == []
    env.bridge.reset_all()  # slot → commit_queue → wake
    await env.sleep(0.1)
    assert env.bridge.state.images[0].status == "completed"
    assert len(env.recs["job_started"].calls) == 1
    assert any("🏁 Pass complete — run stays live (0 queued)" in m for m in logs(env))
    assert not task.done() and env.bridge._run_state == "running"  # the pass ended, the run did not
    env.bridge._stop_after = True
    live_bus(env.bridge).wake("test")
    await settle(task)
    assert env.bridge._run_state == "idle"


def cooling_pool():
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(tab_id="tab1", ws_url="ws://x", title="T", url="https://arena.ai", is_connected=True))
    page = pool.get_page("tab1")  # `add_page` registers a steady page; the timer is set on the live object
    page.status, page.cooldown_until = PageStatus.COOLDOWN, time.time() + 600
    return pool


@pytest.mark.parametrize("reason, arrange", [
    ("no tab", lambda env: None),
    ("all cooling", lambda env: None),
    ("cdp down", lambda env: setattr(env.cdp, "is_connected", False)),
])
@pytest.mark.asyncio
async def test_no_tab_all_cooling_and_cdp_down_are_wait_states(tmp_path, monkeypatch, reason, arrange):
    kw = {"cdp": FakeCDP(tab_id="")} if reason == "no tab" else {}
    if reason == "all cooling":
        kw["pool"] = cooling_pool()
    env = live_env(tmp_path, monkeypatch, **kw)
    arrange(env)
    plan = await sv.plan_pass(env.bridge)
    assert plan.reason == reason and len(plan.images) == 1
    task = asyncio.ensure_future(sv.run_live(env.bridge))
    await env.sleep(0.06)
    assert not task.done() and env.bridge._run_state == "running"
    head = sv.REASON_LINES[reason][0].split("{")[0]
    assert sum(m.startswith(head) for m in logs(env)) == 1
    assert env.recs["job_started"].calls == []  # a wait state never dispatches
    env.bridge._cancel_requested = True
    task.cancel()
    await settle(task)


@pytest.mark.asyncio
async def test_stop_is_the_only_way_out(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch)
    park_all(env.bridge)
    task = asyncio.ensure_future(sv.run_live(env.bridge))
    env.bridge._batch_future = task
    await env.sleep(0.02)
    assert json.loads(env.bridge.cancel_current())["ok"] is True
    await settle(task)
    assert task.done() and env.bridge._run_state == "idle" and env.bridge.state.run_state == "idle"
    assert any("🏁 Batch cancelled" in m for m in logs(env))


@pytest.mark.asyncio
async def test_a_crashing_pass_ends_the_loop_loudly_and_idles(tmp_path, monkeypatch):
    """RULE 4: an unexpected exception inside a pass is named in the log, the loop ends, run_state is idle.

    Would fail if `_crash_tail` were deleted (no `Batch runner crashed` line) or if the
    `except Exception` branch were dropped (the task would raise instead of finishing)."""
    env = live_env(tmp_path, monkeypatch)

    async def boom(_bridge, _plan):
        raise RuntimeError("pipeline exploded")
    monkeypatch.setattr(sv, "run_pass", boom)
    task = asyncio.ensure_future(sv.run_live(env.bridge))
    await settle(task)
    assert task.done() and task.exception() is None
    crash = [m for m in logs(env) if "Batch runner crashed" in m]
    assert crash == ["Batch runner crashed: pipeline exploded"]
    assert env.bridge._run_state == "idle" and env.bridge.state.run_state == "idle"
    assert not any("🏁 Batch cancelled" in m for m in logs(env))  # a crash is not a cancel


@pytest.mark.asyncio
async def test_stop_after_current_finishes_the_pass_then_ends(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch, n_images=2)
    arm_hooks(env, after_finish=lambda e: setattr(e.bridge, "_stop_after", True))
    await asyncio.wait_for(sv.run_live(env.bridge), 5)
    assert [i.status for i in env.bridge.state.images] == ["completed", "pending"]
    assert any(m.startswith("🏁 Batch complete") for m in logs(env))
    assert env.bridge._run_state == "idle"


@pytest.mark.asyncio
async def test_run_state_has_exactly_one_writer(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch)
    arm_hooks(env, after_finish=lambda e: setattr(e.bridge, "_stop_after", True))
    seen, real = [], sv.set_run_state
    monkeypatch.setattr(sv, "set_run_state", lambda b, v: seen.append(v) or real(b, v))
    await asyncio.wait_for(sv.run_live(env.bridge), 5)
    assert seen == ["running", "idle"]
    assert (env.bridge._run_state, env.bridge.state.run_state) == ("idle", "idle")  # L-2: persisted value is honest
    for rel in ("services/batch_orchestrator.py", "services/multi_page_dispatcher.py"):
        src = (APP / rel).read_text(encoding="utf-8")
        assert not re.search(r"_run_state\s*=", src), rel
    slots = (APP / "ui/panels/run_control.py").read_text(encoding="utf-8")
    assert "self._run_state =" not in slots  # the slots go through set_run_state too


def test_start_while_live_wakes_instead_of_refusing(tmp_path, monkeypatch):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=2)
    monkeypatch.setattr(run_control, "schedule_batch", lambda *a: pytest.fail("a live run must not be scheduled twice"))
    env.bridge._run_state = "running"
    env.bridge._batch_future = asyncio.new_event_loop().create_future()  # alive
    res = json.loads(env.bridge.start_run())
    assert res == {"ok": True, "live": True}
    lines = logs(env)
    assert not any("Already running" in m or "batch still active" in m for m in lines)
    assert sum(m.startswith("🟢 Run already live") and "(2 queued)" in m for m in lines) == 1
    assert "start" in live_bus(env.bridge).reasons()


def test_folder_ai_is_refused_only_while_an_image_processes(tmp_path):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    env.bridge._run_state = "running"  # live but idle: allowed (the old "run is idle" guard is permanently closed, D-5)
    assert json.loads(queue_scan.run_folder_ai_request(env.bridge, "only")).get("error") != sv.PROCESSING_REFUSAL
    env.bridge.state.images[0].status = "processing"
    assert json.loads(queue_scan.run_folder_ai_request(env.bridge, "only")) == {"ok": False, "error": sv.PROCESSING_REFUSAL}


@pytest.mark.asyncio
async def test_failed_images_retry_up_to_max_attempts_then_rest(tmp_path, monkeypatch):
    """A live loop re-plans every pass, so `failed` obeys `settings.retries.max_attempts`; Retry (→ pending) always runs."""
    env = live_env(tmp_path, monkeypatch, n_images=3)
    env.bridge.state.settings.retries["max_attempts"] = 2
    worn, fresh, retried = env.bridge.state.images
    worn.status, worn.attempt_count = "failed", 2
    fresh.status, fresh.attempt_count = "failed", 1
    retried.status, retried.attempt_count = "pending", 9
    plan = await sv.plan_pass(env.bridge)
    assert [i.id for i in plan.images] == [fresh.id, retried.id]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_goldens_are_byte_identical_under_the_supervisor(tmp_path, monkeypatch):
    assert set(RUNNERS) == {"supervisor"}  # the golden file runs every scenario through the supervisor
    patched = install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=2)
    await RUNNERS["supervisor"](env)
    check_golden("happy_two", collect_trace(env, patched.clicks))
    root = tmp_path / "notab"
    root.mkdir()
    patched = install_patches(monkeypatch)  # fresh click recorder for the second scenario
    env = build_bridge(root, build_stack(CORE_STACK), n_images=1, cdp=FakeCDP(tab_id=""))
    await RUNNERS["supervisor"](env)
    trace = collect_trace(env, patched.clicks)
    check_golden("no_tab", trace)
    assert trace["run_state"] == "idle" and trace["events"] == []
