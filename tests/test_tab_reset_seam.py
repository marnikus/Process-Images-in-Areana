"""The reset pipeline at its real seams — RED-first (2026-09-21).

The user's report crossed three seams at once: the URL row's buttons → the Qt
slots → the pool/service state, and Cancel → the doomed batch future → the tabs
that were mid-job. These tests drive the REAL slots and the REAL run loop with
the shipped scheduling seam (no injected `_schedule_coro`, L-6):

* `PagePoolMixin.stop_tab_job` / `reset_page_cooldown` on a real `PagePool`,
* `RunControlMixin.cancel_current` (the button) on the real `Bridge`,
* `run_live` + the dispatcher cancelling a job that is blocked mid-generation —
  the snapshot the UI reads afterwards must be a parked tab, never a stuck one.
"""

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import tab_reset as tr
from app.services.live import supervisor as sv
from app.services.live.bus import LiveBus
from app.ui.panels import page_pool as pp
from tests.characterization.fakes import install_patches
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.integration

BASE = 300


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class Host(pp.PagePoolMixin):
    """The real pool panel mixin on a bare host (no injected private seams)."""

    def __init__(self, pool, scheduled=None):
        self._page_pool = pool
        self.logs = []
        self._log = lambda msg, level="info": self.logs.append((level, msg))
        self.page_pool_updated = Emitter()
        self._emit_pool_status = lambda: self.logs.append(("emit", ""))
        self._persist_cooldowns = lambda: self.logs.append(("persist", ""))
        self.config = SimpleNamespace(get_state=lambda k, d=None: d)
        self._batch_future = None
        self._scheduled = scheduled if scheduled is not None else []


def make_pool(*tab_ids):
    pool = PagePool()
    for tab_id in tab_ids or ("t1",):
        pool.add_page(PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                               url="https://arena.ai/", is_connected=True))
    return pool


def stale(pool, tab_id="t1", image="icon.png"):
    page = pool.get_page(tab_id)
    page.status = PageStatus.BUSY
    page.current_image = image
    page.current_job_id = "job-1"
    return page


def logs_of(host):
    return " | ".join(m for _l, m in host.logs)


@pytest.fixture
def scheduled(monkeypatch):
    """Capture the park coroutines the slots schedule on the real seam."""
    calls = []
    monkeypatch.setattr(tr, "schedule_coro", lambda bridge, coro: calls.append(coro))
    return calls


async def drain(calls, monkeypatch):
    async def ok(ctx):
        return True, "mock"
    monkeypatch.setattr(tr, "reset_to_new_chat", ok)
    for coro in calls:
        await coro


# ---- the pool panel slots ---------------------------------------------------

@pytest.mark.asyncio
async def test_stop_slot_parks_a_stale_tab_and_replies_honestly(scheduled, monkeypatch):
    pool = make_pool()
    host = Host(pool)
    page = stale(pool)

    reply = json.loads(host.stop_tab_job("t1"))

    assert reply == {"ok": True, "mode": "reset", "seconds": BASE}
    assert "Stop requested for job" not in logs_of(host), "never claim a job that is not there"
    await drain(scheduled, monkeypatch)
    assert page.status == PageStatus.COOLDOWN and page.current_image is None
    snap = json.loads(host.get_page_pool_status())
    assert snap["free"] == 0 and snap["cooling"] == 1


@pytest.mark.asyncio
async def test_stop_slot_aborts_a_live_job(scheduled, monkeypatch):
    pool = make_pool()
    host = Host(pool)
    host._batch_future = asyncio.get_running_loop().create_future()
    page = stale(pool)
    reply = json.loads(host.stop_tab_job("t1"))
    assert reply == {"ok": True, "mode": "abort"}
    assert scheduled == []
    assert page.status == PageStatus.BUSY, "the job's own finish parks it"
    page.current_image = None


def test_stop_slot_refuses_an_idle_tab(scheduled):
    host = Host(make_pool())
    assert json.loads(host.stop_tab_job("t1")) == {"ok": False, "error": "no live job on this tab"}


def test_stop_slot_parks_on_the_real_background_seam():
    """The reported dead end, end to end: Stop with no live run must REALLY park.

    No injected `schedule_coro` here — the shipped seam (`ensure_bg_loop` +
    `run_coroutine_threadsafe`) runs the park, exactly as in the app.
    """
    pool = make_pool()
    host = Host(pool)
    page = stale(pool)
    reply = json.loads(host.stop_tab_job("t1"))
    assert reply == {"ok": True, "mode": "reset", "seconds": BASE}
    deadline = time.monotonic() + 5
    while page.status != PageStatus.COOLDOWN and time.monotonic() < deadline:
        time.sleep(0.05)
    assert page.status == PageStatus.COOLDOWN, "the park must not stay a promise"
    assert page.current_image is None and page.current_job_id is None
    assert page.remaining_seconds() > 0, "the tab is cooling, not free"
    assert "cooling" in logs_of(host)


def test_clear_slot_repairs_a_stale_tab_and_reports_it():
    pool = make_pool()
    host = Host(pool)
    page = stale(pool)
    reply = json.loads(host.reset_page_cooldown("t1"))
    assert reply["ok"] is True and reply["job_cleared"] is True
    assert page.is_free() and page.current_image is None
    snap = json.loads(host.get_page_pool_status())
    assert snap["free"] == 1 and snap["busy"] == 0
    assert "ready now" in logs_of(host)


def test_clear_slot_reports_the_seconds_it_removed():
    pool = make_pool()
    host = Host(pool)
    page = pool.get_page("t1")
    page.status = PageStatus.COOLDOWN
    page.cooldown_until = __import__("time").time() + 271
    page.cooldown_total = 271
    reply = json.loads(host.reset_page_cooldown("t1"))
    assert 265 <= reply["was"] <= 271 and page.remaining_seconds() == 0


def test_clear_slot_is_honest_when_a_job_is_running():
    pool = make_pool()
    host = Host(pool)
    host._batch_future = SimpleNamespace(done=lambda: False)
    page = stale(pool, image="running.png")
    reply = json.loads(host.reset_page_cooldown("t1"))
    assert reply == {"ok": True, "was": 0, "busy": True, "job_cleared": False}
    assert page.current_image == "running.png"


# ---- the run-control cancel slot -------------------------------------------

def test_cancel_current_schedules_the_sweep(monkeypatch):
    calls = []
    monkeypatch.setattr(tr, "schedule_coro", lambda bridge, coro: calls.append(coro))
    from app.ui.panels.run_control import RunControlMixin

    class RunHost(RunControlMixin):
        def __init__(self):
            self._cancel_requested = False
            self._pause_requested = False
            self._stop_after = False
            self._run_state = "running"
            self._batch_future = None
            self.state = SimpleNamespace(images=[], urls=[], run_state="running",
                                        recalculate_progress=lambda: None)
            self._page_pool = make_pool()
            self.logs = []
            self._log = lambda m, l="info": self.logs.append((m, l))
            self._save_arena = lambda: None

        def _emit_arena_state(self):
            pass

    host = RunHost()
    reply = json.loads(host.cancel_current())
    assert reply == {"ok": True}
    assert host._cancel_requested is True
    assert len(calls) == 1, "the reset pipeline is scheduled, not run on the ws thread"
    assert any("Cancel" in m for m, _l in host.logs)
    for coro in calls:
        coro.close()  # the sweep itself is covered below


# ---- end to end: Cancel pressed while a job is mid-generation ---------------

class FakeClock:
    def __call__(self):
        return 1000.0


@pytest.mark.asyncio
async def test_cancel_mid_job_leaves_every_tab_parked_not_stuck(tmp_path, monkeypatch):
    """The reported sequence, end to end: run → job in flight → Cancel → Stop.

    After the cancel the row must not keep its `▶ image` line, the tab must not
    stay busy forever, and it must sit in a real countdown (the new-chat reset
    and the park are the user's requested pipeline).
    """
    patched = install_patches(monkeypatch)
    pool = make_pool("tab1")
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=2,
                       tab_ids=["tab1"], pool=pool)
    bridge = env.bridge
    monkeypatch.setattr(sv, "WAIT_S", 0.005)
    real_sleep = asyncio.sleep

    async def yield_only(_s):
        await real_sleep(0)
    monkeypatch.setattr(asyncio, "sleep", yield_only)
    bridge._live_bus = LiveBus(clock=FakeClock())
    bridge._batch_future = None

    started, hold = asyncio.Event(), asyncio.Event()
    real_baseline = patched.ctrl.capture_baseline

    async def slow_baseline():
        started.set()
        await hold.wait()
        return await real_baseline()

    patched.ctrl.capture_baseline = slow_baseline
    scheduled = []
    monkeypatch.setattr(tr, "schedule_coro", lambda bridge_, coro: scheduled.append(coro))

    task = asyncio.ensure_future(sv.run_live(bridge))
    await asyncio.wait_for(started.wait(), 5)
    page = pool.get_page("tab1")
    assert page.current_image, "the job really is in flight"
    bridge._batch_future = task          # what schedule_batch records (I-45)

    reply = json.loads(bridge.cancel_current())   # the Cancel current button
    assert reply["ok"] is True

    await real_sleep(0)
    hold.set()
    for coro in scheduled:               # the panel's scheduled sweep (bg loop in the app)
        await coro
    try:
        await asyncio.wait_for(task, 5)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    assert page.current_image is None, "the row loses its ▶ image line"
    assert page.status != PageStatus.BUSY, "no tab is left stuck after a cancel"
    assert page.remaining_seconds() > 0, "the cancel parks the tab in a real countdown"
    assert page.status == PageStatus.COOLDOWN
    assert bridge._run_state == "idle"
