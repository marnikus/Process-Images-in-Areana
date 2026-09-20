"""live.supervisor — the always-live run (S5, D-5/D-8, I-47).

`run_live` replaces "one batch then idle": no work / no tab / CDP down are
wait states on S4's bus, a pass runs whenever there is work, and the run ends
only on Stop-after-current or Cancel. `set_run_state` is the only writer of
`_run_state` (D-8 / L-2). Real Bridge from the golden harness, real
orchestrator with the harness fakes at the CDP boundary; the only knob
touched is the bus wait (`WAIT_S`), shortened so a test lasts milliseconds.
"""

import asyncio
import json
import re
from concurrent.futures import Future
from pathlib import Path

import pytest

from app.services.live import feed, supervisor
from app.services.live.bus import live_bus
from tests.characterization import harness
from tests.characterization.fakes import FakeCDP, install_patches
from tests.characterization.harness import arm_hooks, build_bridge, build_stack, make_images
from tests.characterization.test_batch_goldens import CORE_STACK

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[1]


def quick_waits(monkeypatch):
    monkeypatch.setattr(supervisor, "WAIT_S", 0.01)


def logs_of(env):
    return [m for m, _lvl in env.recs["arena_log"].calls]


def live_env(tmp_path, monkeypatch, n_images=0, cdp=None):
    install_patches(monkeypatch)
    quick_waits(monkeypatch)
    return build_bridge(tmp_path, build_stack(CORE_STACK), n_images=n_images, cdp=cdp)


async def start_live(env):
    task = asyncio.ensure_future(supervisor.run_live(env.bridge))
    env.bridge._batch_future = task
    await asyncio.sleep(0.05)
    return task


async def stop_live(env, task):
    env.bridge._stop_after = True
    live_bus(env.bridge).wake("test-stop")
    await asyncio.wait_for(task, timeout=5)


async def test_no_work_waits_and_never_ends(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch, n_images=0)
    task = await start_live(env)
    await asyncio.sleep(0.2)                     # ≈ 20 bus waits
    assert not task.done()
    assert env.bridge._run_state == "running"
    assert supervisor.live_state(env.bridge).reason == "no_work"
    lines = [m for m in logs_of(env) if "Run live" in m and "0 queued" in m]
    assert len(lines) == 1, lines                 # throttled: once per window, not once per wait
    await stop_live(env, task)
    assert env.bridge._run_state == "idle"
    assert any("🏁 Batch complete" in m for m in logs_of(env))


async def test_new_work_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch, n_images=0)
    task = await start_live(env)
    env.bridge.state.images = make_images(tmp_path, 1)
    feed.commit_queue(env.bridge, "scan")         # the funnel wakes the loop
    for _ in range(600):                           # the harness pass has real 1 s post-job sleeps
        if env.bridge.state.images[0].status == "completed":
            break
        await asyncio.sleep(0.02)
    assert env.bridge.state.images[0].status == "completed"
    for _ in range(300):                           # the pass tail (post-job cooldown sleep) is still running
        if supervisor.live_state(env.bridge).passes:
            break
        await asyncio.sleep(0.02)
    assert not task.done()                         # the run is still live after the pass
    assert supervisor.live_state(env.bridge).passes == 1
    assert any("✅ Pass complete — 1 planned, 0 still queued" in m for m in logs_of(env))
    await stop_live(env, task)


@pytest.mark.parametrize("scenario,expected", [("no_tab", "no_tab"), ("cdp_down", "cdp_down")])
async def test_no_tab_and_cdp_down_are_wait_states(tmp_path, monkeypatch, scenario, expected):
    cdp = FakeCDP(tab_id="") if scenario == "no_tab" else FakeCDP()
    env = live_env(tmp_path, monkeypatch, n_images=1, cdp=cdp)
    if scenario == "cdp_down":
        env.cdp.is_connected = False
    task = await start_live(env)
    await asyncio.sleep(0.1)
    assert not task.done() and env.bridge._run_state == "running"
    assert supervisor.live_state(env.bridge).reason == expected
    assert len([m for m in logs_of(env) if "Run live" in m]) == 1
    assert env.bridge.state.images[0].status == "pending"   # nothing was sent
    await stop_live(env, task)


async def test_cancel_ends_the_run(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch, n_images=0)
    task = await start_live(env)
    json.loads(env.bridge.cancel_current())        # the real slot: flag + future.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
    assert env.bridge._run_state == "idle"
    assert any("🏁 Batch cancelled" in m for m in logs_of(env))


async def test_stop_after_current_finishes_the_pass_then_ends(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch, n_images=2)
    arm_hooks(env, after_finish=lambda e: setattr(e.bridge, "_stop_after", True))
    await asyncio.wait_for(supervisor.run_live(env.bridge), timeout=10)   # ends on its own
    statuses = [im.status for im in env.bridge.state.images]
    assert statuses == ["completed", "pending"]
    assert env.bridge._run_state == "idle"
    assert any("🏁 Batch complete" in m for m in logs_of(env))            # the pinned marker


async def test_run_state_has_exactly_one_writer(tmp_path, monkeypatch):
    for rel in ("app/services/batch_orchestrator.py", "app/services/multi_page_dispatcher.py",
                "app/ui/panels/run_control.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r"_run_state\s*=(?!=)", src), f"{rel} assigns _run_state (D-8: supervisor.set_run_state only)"
    env = live_env(tmp_path, monkeypatch, n_images=1)
    seen = []
    real = supervisor.set_run_state
    monkeypatch.setattr(supervisor, "set_run_state", lambda b, v: seen.append(v) or real(b, v))
    arm_hooks(env, after_finish=lambda e: setattr(e.bridge, "_stop_after", True))
    await asyncio.wait_for(supervisor.run_live(env.bridge), timeout=10)
    assert seen == ["running", "idle"]
    assert env.bridge.state.run_state == "idle"     # L-2: AppState.run_state is written too


def test_start_while_live_wakes_instead_of_refusing(tmp_path, monkeypatch):
    env = live_env(tmp_path, monkeypatch, n_images=1)
    bridge = env.bridge
    bridge._batch_future = Future()                 # alive ⇒ the run is live
    bridge._run_state, bridge._pause_requested, bridge._stop_after = "paused", True, True
    res = json.loads(bridge.start_run())
    assert res["ok"] is True and res["live"] is True and res["queued"] == 1
    assert live_bus(bridge).reasons() == ["start"]
    assert (bridge._pause_requested, bridge._stop_after, bridge._run_state) == (True, True, "paused")
    assert any("🟢 Run already live — queue re-checked (1 queued)" in m for m in logs_of(env))
    assert not any("Already running" in m for m in logs_of(env))


def test_folder_ai_is_refused_only_while_an_image_processes(tmp_path):
    from app.ui.panels.queue_scan import run_folder_ai_request
    from tests.test_batch_orchestrator import make_bridge as bare_bridge
    from tests.test_multi_page_dispatcher_run import make_img

    img = make_img()
    img.status = "pending"
    bridge = bare_bridge(images=[img])
    bridge.state.folder = {}
    bridge._scan_in_progress = False
    assert json.loads(run_folder_ai_request(bridge, "strip"))["error"] == "No folder set"  # past the guard
    img.status = "processing"
    assert json.loads(run_folder_ai_request(bridge, "strip"))["error"] == "an image is processing — wait or Cancel first"


def test_the_goldens_run_under_the_supervisor():
    assert list(harness.RUNNERS) == ["supervisor"]
    assert not hasattr(harness, "run_orchestrator")


def test_tails_write_idle_and_say_why(capsys):
    """The three ways a run ends, each idle + emitted (moved here from the orchestrator, S5)."""
    from tests.test_batch_orchestrator import make_bridge as bare_bridge

    bridge = bare_bridge()
    supervisor.end_tail(bridge)
    assert any("🏁 Batch complete" in m for m, _ in bridge._logs) and bridge._run_state == "idle"
    bridge._cancel_requested = True
    supervisor.end_tail(bridge)
    assert any("🏁 Batch cancelled by user" in m for m, _ in bridge._logs)
    bridge = bare_bridge()
    supervisor.cancelled_tail(bridge)
    assert any("🏁 Batch cancelled" in m for m, _ in bridge._logs) and bridge._run_state == "idle"
    supervisor.crashed_tail(bridge, RuntimeError("Cancelled mid-air"))
    assert any("🏁 Batch cancelled: Cancelled mid-air" in m for m, _ in bridge._logs)
    supervisor.crashed_tail(bridge, RuntimeError("boom"))
    assert any("Batch runner crashed: boom" in m for m, _ in bridge._logs)
    assert bridge._logs.count(("arena", "")) == 3          # every tail emits


async def test_run_live_shell_maps_cancel_and_crash(monkeypatch):
    from tests.test_batch_orchestrator import make_bridge as bare_bridge

    async def raise_cancel(bridge):
        raise asyncio.CancelledError()

    async def raise_err(bridge):
        raise RuntimeError("x")

    bridge = bare_bridge()
    monkeypatch.setattr(supervisor, "plan_pass", raise_cancel)
    with pytest.raises(asyncio.CancelledError):
        await supervisor.run_live(bridge)
    assert bridge._run_state == "idle" and any("🏁 Batch cancelled" in m for m, _ in bridge._logs)
    bridge = bare_bridge()
    monkeypatch.setattr(supervisor, "plan_pass", raise_err)
    await supervisor.run_live(bridge)                       # crash → finalized, not raised
    assert bridge._run_state == "idle" and any("Batch runner crashed: x" in m for m, _ in bridge._logs)
