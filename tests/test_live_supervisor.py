# ideal-size: ~230 lines reason=S5 RED budget — one test per supervisor contract (tdd-interfaces rev-3, 9 tests)
"""S5 RED — the always-live run (`live/supervisor.run_live`).

The run survives no-work / no-tab / all-cooling / CDP-down by waiting on
S4's bus; stop/cancel is the only way out; exactly one writer owns
`_run_state` (D-8, fixes L-2); Start while live wakes instead of refusing;
folder-AI is refused only while an image processes (D-5); the 12 goldens
stay byte-identical under the supervisor runner.
"""

import asyncio
import contextlib
from concurrent.futures import Future

import pytest

from tests.characterization.fakes import FakeCDP, install_patches
from tests.characterization.harness import CORE_STACK, build_bridge, arm_hooks


@pytest.mark.asyncio
async def test_no_work_waits_and_never_ends(tmp_path, monkeypatch):
    from app.services.live import supervisor
    from app.services.live.bus import live_bus

    ns = build_bridge(tmp_path, stack=[], n_images=0)
    bridge = ns.bridge
    monkeypatch.setattr(supervisor, "WAIT_S", 0.02)
    now = {"t": 0.0}
    live_bus(bridge)._clock = lambda: now["t"]

    task = asyncio.ensure_future(supervisor.run_live(bridge))
    await asyncio.sleep(0.05)
    assert not task.done(), "no work must wait, never end"
    assert bridge._run_state == "running"
    lines = [m for m, _ in ns.recs["arena_log"].calls if "Run live" in m]
    assert len(lines) == 1 and "0 queued images" in lines[0]

    now["t"] = 60.0  # a minute of fake time passes
    await asyncio.sleep(0.1)
    lines = [m for m, _ in ns.recs["arena_log"].calls if "Run live" in m]
    assert len(lines) == 1, "the wait line is throttled to one per window"
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


@pytest.mark.asyncio
async def test_new_work_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    from app.core.models import ImageItem
    from app.services.live import supervisor
    from app.services.live.feed import commit_queue

    ns = build_bridge(tmp_path, stack=[], n_images=0)
    bridge = ns.bridge
    monkeypatch.setattr(supervisor, "WAIT_S", 0.02)
    runs = []

    async def spy_pass(b, plan):
        runs.append(plan)

    monkeypatch.setattr(supervisor, "run_pass", spy_pass)
    task = asyncio.ensure_future(supervisor.run_live(bridge))
    await asyncio.sleep(0.05)
    assert runs == []  # still waiting on the empty queue

    img = ImageItem(id="late", relative_path="late.png", absolute_path=str(tmp_path / "late.png"),
                    filename="late.png", base_name="late", extension=".png",
                    size=1, mtime=1.0, fingerprint="fplate",
                    status="pending", selected=True)
    bridge.state.images.append(img)
    commit_queue(bridge, "reset_all")  # the funnel's wake is the pickup signal
    await asyncio.sleep(0.05)
    assert len(runs) == 1 and runs[0].images == [img]
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["no_tab", "all_cooling", "cdp_down"])
async def test_wait_states_keep_the_run_alive(tmp_path, monkeypatch, reason):
    from app.services.live import supervisor

    cdp = FakeCDP(tab_id="") if reason == "no_tab" else None
    pool = None
    if reason == "all_cooling":
        from app.browser.page_pool import PagePool
        from app.browser.page_status import PageInfo, PageStatus
        pool = PagePool(logger=lambda m, l="info": None)
        pool.add_page(PageInfo(tab_id="tab1", ws_url="ws://x", title="Arena",
                               url="https://arena.ai/chat"))
        page = pool.get_page("tab1")
        page.status = PageStatus.COOLDOWN
        page.cooldown_until = 9999999999.0
    ns = build_bridge(tmp_path, stack=[], n_images=1, pool=pool,
                      **({"cdp": cdp} if cdp else {}))
    bridge = ns.bridge
    if reason == "cdp_down":
        bridge.cdp.is_connected = False
    monkeypatch.setattr(supervisor, "WAIT_S", 0.02)
    seen = []

    async def spy_wait(b, plan, bus):
        seen.append(plan.reason)
        await bus.wait(0.01)

    monkeypatch.setattr(supervisor, "wait_reason", spy_wait)
    task = asyncio.ensure_future(supervisor.run_live(bridge))
    await asyncio.sleep(0.05)
    assert not task.done() and bridge._run_state == "running"
    assert seen and set(seen) == {reason}
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


@pytest.mark.asyncio
async def test_stop_is_the_only_way_out(tmp_path, monkeypatch):
    from app.services.live import supervisor
    from app.services.live.bus import live_bus

    ns = build_bridge(tmp_path, stack=[], n_images=1)
    bridge = ns.bridge
    monkeypatch.setattr(supervisor, "WAIT_S", 0.02)

    async def holding_pass(b, plan):
        await live_bus(b).wait(1.0)  # park inside a "pass" until woken

    monkeypatch.setattr(supervisor, "run_pass", holding_pass)
    task = asyncio.ensure_future(supervisor.run_live(bridge))
    await asyncio.sleep(0.05)
    assert not task.done()

    bridge._cancel_requested = True
    live_bus(bridge).wake("cancel")
    await asyncio.wait_for(task, 2.0)
    assert bridge._run_state == "idle"
    assert any("Batch cancelled" in m for m, _ in ns.recs["arena_log"].calls)


@pytest.mark.asyncio
async def test_stop_after_current_finishes_the_pass_then_ends(tmp_path, monkeypatch):
    from app.services.live import supervisor

    ns = build_bridge(tmp_path, stack=[], n_images=1)
    bridge = ns.bridge
    monkeypatch.setattr(supervisor, "WAIT_S", 0.02)

    async def pass_where_operator_stops(b, plan):
        b._stop_after = True  # mid-pass: finish this pass, then end

    monkeypatch.setattr(supervisor, "run_pass", pass_where_operator_stops)
    await asyncio.wait_for(supervisor.run_live(bridge), 2.0)
    assert bridge._run_state == "idle"
    assert any("Batch complete" in m for m, _ in ns.recs["arena_log"].calls)


@pytest.mark.asyncio
async def test_a_crashing_pass_ends_the_run_honestly(tmp_path, monkeypatch):
    from app.services.live import supervisor

    ns = build_bridge(tmp_path, stack=[], n_images=1)
    bridge = ns.bridge

    async def crashing_pass(b, plan):
        raise RuntimeError("boom")

    monkeypatch.setattr(supervisor, "run_pass", crashing_pass)
    await asyncio.wait_for(supervisor.run_live(bridge), 2.0)  # ends, not raised
    assert bridge._run_state == "idle"
    assert any("Batch runner crashed" in m for m, _ in ns.recs["arena_log"].calls)


@pytest.mark.asyncio
async def test_run_state_has_exactly_one_writer(tmp_path, monkeypatch):
    from pathlib import Path
    from app.services.live import supervisor
    from tests.characterization.harness import build_stack

    patched = install_patches(monkeypatch)
    ns = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1)
    bridge = ns.bridge
    arm_hooks(ns, after_finish=lambda e: setattr(e.bridge, "_stop_after", True))
    writes = []
    real = supervisor.set_run_state

    def spy(b, value):
        writes.append(value)
        real(b, value)

    monkeypatch.setattr(supervisor, "set_run_state", spy)
    await asyncio.wait_for(supervisor.run_live(bridge), 5.0)
    assert writes[0] == "running" and writes[-1] == "idle"
    assert set(writes) == {"running", "idle"}  # every change went through the spy

    for name in ("app/services/batch_orchestrator.py", "app/services/multi_page_dispatcher.py"):
        src = (Path(__file__).parent.parent / name).read_text()
        assert "_run_state =" not in src, f"{name} must not write run state (L-2 lock)"


@pytest.mark.asyncio
async def test_start_while_live_wakes_instead_of_refusing(tmp_path):
    from app.services.live.bus import live_bus
    import json

    ns = build_bridge(tmp_path, stack=[], n_images=1)
    bridge = ns.bridge
    bridge._batch_future = Future()  # a live run is out there

    res = json.loads(bridge.start_run())

    assert res.get("ok") is True, "Start while live must not refuse"
    assert not any("Already running" in m for m, _ in ns.recs["arena_log"].calls)
    assert any("Run already live" in m for m, _ in ns.recs["arena_log"].calls)
    assert "start" in "+".join(live_bus(bridge).reasons())


def test_folder_ai_is_refused_only_while_an_image_processes(tmp_path):
    import json
    from app.ui.panels import queue_scan as qs

    ns = build_bridge(tmp_path, stack=[], n_images=1)
    bridge = ns.bridge
    bridge._run_state = "running"  # live but idle — folder tools must work (D-5)

    res = json.loads(qs.run_folder_ai_request(bridge, "enhance"))
    assert res.get("error") != "stop the run first"  # passed the run guard

    bridge.state.images[0].status = "processing"
    res = json.loads(qs.run_folder_ai_request(bridge, "enhance"))
    assert res["ok"] is False and res["error"] == "stop the run first"


@pytest.mark.asyncio
async def test_goldens_are_byte_identical_under_the_supervisor(tmp_path_factory, monkeypatch):
    import tests.characterization.harness as h
    from tests.characterization import test_batch_goldens as g

    monkeypatch.setattr(h, "RUNNERS", {"supervisor": h.run_supervisor})
    scenarios = (
        g.test_happy_full_stack, g.test_happy_two_images, g.test_disabled_blocks_skipped,
        g.test_nonrequired_midfail_continues, g.test_required_midfail_breaks_job,
        g.test_cancel_before_next_block, g.test_stop_after_current, g.test_captcha_pause_resume,
        g.test_tab_abort_fails_job, g.test_unknown_block_skipped, g.test_custom_find_fallback,
        g.test_no_usable_tab,
    )
    for fn in scenarios:
        await fn(tmp_path_factory.mktemp("sup"), monkeypatch)
