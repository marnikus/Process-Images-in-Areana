"""S5: the always-live run — wait on the bus, pass on work, end only on stop.

No fake clock (S3/S4 finding: it cannot advance time) — wait-state tests use
real short sleeps, and golden scenarios run the real rig (`install_patches` +
`FakeCDP`). There is no `FakeActionRunner` in the tree; the golden rig is it.
"""

import asyncio
import contextlib
from concurrent.futures import Future

import pytest

import app.services.live.supervisor as sv
from app.browser.page_pool import PagePool
from app.services.cooldown_service import start_cooldown
from app.services.live.bus import live_bus
from app.services.live.feed import commit_queue
from tests.characterization.fakes import FakeCDP, install_patches
from tests.characterization.harness import (
    CORE_STACK,
    arm_hooks,
    build_bridge,
    build_stack,
    check_golden,
    collect_trace,
    make_images,
)
from tests.test_captcha_service import make_info


async def _run_one_pass_and_stop(bridge, monkeypatch, timeout=120):
    """Drive run_live until the first pass ends, then stop (test lever)."""
    real_tail = sv.pass_tail

    def stop_after_one(b, plan):
        out = real_tail(b, plan)
        b._stop_after = True  # batch-like termination: one pass, then end
        return out

    monkeypatch.setattr(sv, "pass_tail", stop_after_one)
    await asyncio.wait_for(sv.run_live(bridge), timeout=timeout)


def _live_lines(env):
    return [m for m, _ in env.recs["arena_log"].calls if m.startswith("🟢 Run live")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_work_waits_and_never_ends(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=0)
    task = asyncio.create_task(sv.run_live(env.bridge))
    await asyncio.sleep(2.2)
    assert not task.done()
    assert env.bridge._run_state == "running"
    assert _live_lines(env) == ["🟢 Run live — 0 queued images"]  # throttled: once
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert env.bridge._run_state == "idle"
    assert any("🏁 Batch cancelled" in m for m, _ in env.recs["arena_log"].calls)


async def _await_completed(img, timeout_s=60):
    for _ in range(int(timeout_s * 10)):
        if img.status == "completed":
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{img.relative_path} never completed (still {img.status})")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_work_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=0)
    task = asyncio.create_task(sv.run_live(env.bridge))
    await asyncio.sleep(0.5)
    assert not task.done()
    env.bridge.state.images.extend(make_images(tmp_path, 1))  # work lands mid-wait
    commit_queue(env.bridge, "test")  # the producer wake; the pass dispatches
    img = env.bridge.state.images[0]
    await _await_completed(img)
    img.status = "failed"  # phase B: reset_all requeues + wakes the same loop
    img.selected = False
    await asyncio.sleep(0.6)
    assert not task.done()
    env.bridge.reset_all()
    await _await_completed(img)
    assert not task.done()  # still live afterwards — the run survives no-work
    assert env.bridge._run_state == "running"
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert env.bridge._run_state == "idle"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_tab_all_cooling_and_cdp_down_are_wait_states(tmp_path):
    async def drive(env, reason):
        assert sv.plan_pass(env.bridge).reason == reason
        task = asyncio.create_task(sv.run_live(env.bridge))
        await asyncio.sleep(1.5)
        assert not task.done()
        assert env.bridge._run_state == "running"
        assert len(_live_lines(env)) == 1
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        assert env.bridge._run_state == "idle"

    pool = PagePool()  # no pages and no current tab: nothing to wait for but a tab
    env = build_bridge(tmp_path, build_stack([]), n_images=1, pool=pool,
                       cdp=FakeCDP(tab_id=""))
    await drive(env, "no_tab")

    pool = PagePool()
    pool.add_page(make_info("t1"))
    start_cooldown(pool, "t1", 300, "test")
    env = build_bridge(tmp_path, build_stack([]), n_images=1, pool=pool,
                       tab_ids=["t1"])
    await drive(env, "all_cooling")

    cdp = FakeCDP()
    cdp.is_connected = False
    env = build_bridge(tmp_path, build_stack([]), n_images=1, cdp=cdp)
    await drive(env, "cdp_down")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_is_the_only_way_out(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=0)
    task = asyncio.create_task(sv.run_live(env.bridge))
    await asyncio.sleep(0.3)
    env.bridge.cancel_current()
    await asyncio.wait_for(task, timeout=30)
    assert env.bridge._run_state == "idle"
    assert any("🏁 Batch cancelled" in m for m, _ in env.recs["arena_log"].calls)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_after_current_finishes_the_pass_then_ends(tmp_path, monkeypatch):
    install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)

    def stop_soon(_env):
        env.bridge._stop_after = True

    arm_hooks(env, after_finish=stop_soon)
    await asyncio.wait_for(sv.run_live(env.bridge), timeout=120)
    assert env.bridge.state.images[0].status == "completed"  # in-flight finished
    assert env.bridge._run_state == "idle"
    assert any("🏁 Batch complete" in m for m, _ in env.recs["arena_log"].calls)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_state_has_exactly_one_writer(tmp_path, monkeypatch):
    from pathlib import Path

    for name in ("batch_orchestrator.py", "multi_page_dispatcher.py"):
        src = (Path("app/services") / name).read_text()
        assert "_run_state =" not in src, f"{name} writes run state (L-2)"
    install_patches(monkeypatch)
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    seen = []
    real_set = sv.set_run_state

    def spy(bridge, value):
        seen.append(value)
        return real_set(bridge, value)

    monkeypatch.setattr(sv, "set_run_state", spy)
    await _run_one_pass_and_stop(env.bridge, monkeypatch)
    assert seen == ["running", "idle"]  # every change came through the spy
    assert env.bridge._run_state == "idle"


@pytest.mark.unit
def test_start_while_live_wakes_instead_of_refusing(tmp_path):
    env = build_bridge(tmp_path, build_stack([]), n_images=1)
    bridge = env.bridge
    bridge._run_state = "running"
    bridge._batch_future = Future()  # alive: the loop is really out there
    import json

    res = json.loads(bridge.start_run())
    assert res.get("ok") is True and res.get("already_live") is True
    assert not any("Already running" in m for m, _ in env.recs["arena_log"].calls)
    assert any("🟢 Run already live" in m for m, _ in env.recs["arena_log"].calls)
    assert live_bus(bridge).reasons() == ["start"]


@pytest.mark.unit
def test_folder_ai_is_refused_only_while_an_image_processes(tmp_path):
    from app.ui.panels.queue_scan import run_folder_ai_request

    env = build_bridge(tmp_path, build_stack([]), n_images=1)
    bridge = env.bridge
    bridge.state.folder = {"root_path": str(tmp_path)}
    bridge._run_state = "running"  # live but idle: allowed
    import json

    assert json.loads(run_folder_ai_request(bridge, "strip"))["pending"] is True
    bridge.state.images[0].status = "processing"
    assert json.loads(run_folder_ai_request(bridge, "strip")) == {
        "ok": False, "error": "stop the run first"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_goldens_are_byte_identical_under_the_supervisor(tmp_path, monkeypatch):
    import tests.characterization.harness as h
    import tests.characterization.test_batch_goldens as g

    monkeypatch.setattr(g, "RUNNERS", {"supervisor": h.run_supervisor})
    scenarios = [g.test_happy_full_stack, g.test_happy_two_images,
                 g.test_disabled_blocks_skipped, g.test_nonrequired_midfail_continues,
                 g.test_required_midfail_breaks_job, g.test_cancel_before_next_block,
                 g.test_stop_after_current, g.test_captcha_pause_resume,
                 g.test_tab_abort_fails_job, g.test_unknown_block_skipped,
                 g.test_custom_find_fallback]
    for i, scenario in enumerate(scenarios):
        sub = tmp_path / f"sv{i}"
        sub.mkdir()
        await asyncio.wait_for(_run_one_pass_and_stop_ctx(scenario, sub, monkeypatch),
                               timeout=180)

    # no_tab waits by design (no pass ever runs): stop it, then the ended trace matches.
    sub = tmp_path / "sv_notab"
    sub.mkdir()
    patched = install_patches(monkeypatch)
    env = build_bridge(sub, build_stack(CORE_STACK), n_images=1, cdp=FakeCDP(tab_id=""))
    task = asyncio.create_task(h.run_supervisor(env))
    await asyncio.sleep(2.0)
    assert not task.done()
    assert env.bridge._run_state == "running"
    env.bridge.cancel_current()
    await asyncio.wait_for(task, timeout=30)
    trace = collect_trace(env, patched.clicks)
    check_golden("no_tab", trace)
    assert trace["events"] == []
    assert trace["run_state"] == "idle"


async def _run_one_pass_and_stop_ctx(scenario, sub, monkeypatch):
    """One golden scenario with batch-like termination (one pass, then end)."""
    real_tail = sv.pass_tail

    def stop_after_one(b, plan):
        out = real_tail(b, plan)
        b._stop_after = True
        return out

    monkeypatch.setattr(sv, "pass_tail", stop_after_one)
    await scenario(sub, monkeypatch)
