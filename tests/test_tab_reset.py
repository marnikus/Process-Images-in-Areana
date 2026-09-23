"""The Stop / Cancel / Clear-time reset pipeline — RED-first (2026-09-21).

User report: after Cancel the row kept its `▶ image` line, the tab stayed busy,
the row's STATUS stayed `unchecked`, no countdown appeared, and pressing Stop
logged `Stop requested for job on …` followed by nothing at all.

Measured root cause (design F-1): `current_image` was trusted as proof of a live
job, so Stop answered `{"ok": true}` and set an abort flag **no live job could
read**, while Clear time refused with "job still running on this tab" — a dead
end where the tab can never become free again.

RULE 8: these tests drive the REAL `PagePool` + the new `tab_reset` service and
read the very snapshot the UI renders.
"""

import time
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool, tab_label_of
from app.browser.page_status import PageInfo, PageStatus
from app.core.cooldown import DEFAULT_MIN_SECONDS
from app.services import cooldown_service as svc
from app.services import tab_reset as tr

pytestmark = pytest.mark.integration

BASE = 300  # the configured pause — the report's "default 5 min or user-configured"


def make_info(tab_id="a"):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url="https://arena.ai/", status=PageStatus.STEADY, is_connected=True)


class FakeFuture:
    """Stands in for `bridge._batch_future` (I-45): alive while the run is live."""

    def __init__(self, done=True):
        self._done = done

    def done(self):
        return self._done


def make_bridge(pool, session=None, live=False):
    state = {"cooldown_enabled": True, "cooldown_min_seconds": BASE,
             "cooldown_captcha_penalty_seconds": 900,
             "cooldown_rate_limit_penalty_seconds": 1800}
    if session:
        state.update(session)
    logs = []
    return SimpleNamespace(
        _page_pool=pool,
        _cancel_requested=False,
        _batch_future=FakeFuture(done=not live),
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        _persist_cooldowns=lambda: logs.append(("persist", "")),
        _logs=logs,
        _session=state,
    )


def make_pool(*tab_ids):
    pool = PagePool()
    for tab_id in tab_ids or ("a",):
        pool.add_page(make_info(tab_id))
    return pool


def stale_busy(pool, tab_id="a", image="icon.png"):
    """The exact state a cancelled job leaves behind: BUSY + a lost image (F-1)."""
    page = pool.get_page(tab_id)
    page.status = PageStatus.BUSY
    page.current_image = image
    page.current_job_id = "job-1"
    return page


def log_text(bridge):
    return " | ".join(m for m, _lvl in bridge._logs)


def capture_park(monkeypatch):
    """Capture the park coroutine the sync entry schedules (the real seam has its
    own test in `test_tab_reset_seam.py`)."""
    calls = []
    monkeypatch.setattr(tr, "schedule_coro", lambda bridge, coro: calls.append(coro))
    return calls


def close_pending(calls):
    """Drop captured-but-unrun coroutines (no 'never awaited' warnings)."""
    for coro in calls:
        coro.close()


async def park_calls(calls, monkeypatch, reset=None):
    """Run the captured park coroutines with the page reset faked at its boundary."""
    async def ok(ctx):
        return True, "mock"
    monkeypatch.setattr(tr, "reset_to_new_chat", reset or ok)
    for coro in calls:
        await coro


# ---- D-2/D-3: Stop means abort or repair — never a lie ----------------------

async def test_stop_with_a_live_job_only_requests_the_abort(monkeypatch):
    """A real job keeps its cooperative abort — Stop must not yank the page."""
    calls = capture_park(monkeypatch)
    pool = make_pool()
    bridge = make_bridge(pool, live=True)
    pool.get_page("a").current_image = "a.png"
    reply = tr.stop_request(bridge, "a")
    assert reply == {"ok": True, "mode": "abort"}
    assert svc.is_tab_aborted(pool, "a") is True
    assert calls == [], "a live job is parked by its own finish, not by Stop"
    assert pool.get_page("a").remaining_seconds() == 0


async def test_stop_on_a_stale_tab_parks_it_instead_of_lying(monkeypatch):
    """RED at 71970e1: the reply was `{"ok": true}` and the page stayed busy forever."""
    calls = capture_park(monkeypatch)
    pool = make_pool()
    bridge = make_bridge(pool)
    page = stale_busy(pool)
    reply = tr.stop_request(bridge, "a")
    assert reply == {"ok": True, "mode": "reset", "seconds": BASE}
    await park_calls(calls, monkeypatch)
    assert page.current_image is None and page.current_job_id is None
    assert page.status == PageStatus.COOLDOWN
    assert BASE - 5 <= page.remaining_seconds() <= BASE
    assert svc.is_tab_aborted(pool, "a") is False, "no job left to abort"
    assert tab_label_of(pool, "a") in log_text(bridge), "the line names the tab readably"


async def test_stop_on_a_free_tab_still_refuses(monkeypatch):
    """An idle tab has nothing to stop — and gets no invented penalty."""
    calls = capture_park(monkeypatch)
    pool = make_pool()
    bridge = make_bridge(pool)
    assert tr.stop_request(bridge, "a") == {"ok": False, "error": "no live job on this tab"}
    assert calls == []
    assert pool.get_page("a").remaining_seconds() == 0


async def test_stop_on_an_unknown_tab_says_so(monkeypatch):
    capture_park(monkeypatch)
    bridge = make_bridge(make_pool())
    assert tr.stop_request(bridge, "ghost") == {"ok": False, "error": "unknown tab"}


async def test_stop_without_a_pool_is_refused(monkeypatch):
    capture_park(monkeypatch)
    bridge = make_bridge(None)
    assert tr.stop_request(bridge, "a") == {"ok": False, "error": "pool not initialized"}


# ---- D-6: the park uses the configured pause --------------------------------

def test_stop_seconds_follow_the_config():
    pool = make_pool()
    assert tr.stop_cancel_seconds(make_bridge(pool)) == BASE
    assert tr.stop_cancel_seconds(make_bridge(pool, {"cooldown_enabled": False})) == 0
    assert tr.stop_cancel_seconds(make_bridge(pool, {"cooldown_min_seconds": 0})) == 0
    assert tr.stop_cancel_seconds(make_bridge(pool, {"cooldown_min_seconds": 600})) == 600
    assert DEFAULT_MIN_SECONDS == 300, "the default the report names (5 min)"


async def test_a_disabled_cooldown_still_repairs_the_page(monkeypatch):
    calls = capture_park(monkeypatch)
    pool = make_pool()
    bridge = make_bridge(pool, {"cooldown_enabled": False})
    page = stale_busy(pool)
    assert tr.stop_request(bridge, "a") == {"ok": True, "mode": "reset", "seconds": 0}
    await park_calls(calls, monkeypatch)
    assert page.status == PageStatus.STEADY and page.is_free()
    assert "no cooldown" in log_text(bridge)


# ---- D-4: Cancel parks every affected tab -----------------------------------

async def test_cancel_parks_every_affected_tab(monkeypatch):
    """RED at 71970e1: Cancel left the tabs busy/steady with no timer at all."""
    pool = make_pool("a", "b", "c")
    bridge = make_bridge(pool)
    busy = stale_busy(pool, "a")
    waiting = pool.get_page("b")
    waiting.status = PageStatus.WAITING_CAPTCHA
    untouched = pool.get_page("c")

    summary = await tr.cancel_run_reset(bridge)

    assert summary["parked"] == 2 and summary["seconds"] == BASE
    assert busy.status == PageStatus.COOLDOWN and busy.current_image is None
    assert waiting.status == PageStatus.COOLDOWN and waiting.remaining_seconds() > 0
    assert untouched.status == PageStatus.STEADY and untouched.remaining_seconds() == 0
    assert "Cancel" in log_text(bridge) and "05:00" in log_text(bridge)
    assert ("emit", "") in bridge._logs and ("persist", "") in bridge._logs


async def test_cancel_never_shortens_a_live_timer(monkeypatch):
    pool = make_pool("a")
    bridge = make_bridge(pool)
    page = stale_busy(pool, "a")
    page.cooldown_until = time.time() + 3600   # a long live countdown
    page.cooldown_total = 3600
    await tr.cancel_run_reset(bridge)
    assert page.remaining_seconds() > BASE + 3000, "the live countdown survives"
    assert page.pending_penalty == 0 and page.current_image is None


async def test_cancel_leaves_a_live_run_to_its_own_finish(monkeypatch):
    """A job that is still unwinding must not be yanked out from under it."""
    monkeypatch.setattr(tr, "UNWIND_WAIT_SEC", 0.0)  # the wait itself is not the subject
    pool = make_pool("a")
    bridge = make_bridge(pool, live=True)
    page = stale_busy(pool, "a")
    summary = await tr.cancel_run_reset(bridge)
    assert summary["parked"] == 0
    assert page.status == PageStatus.BUSY and page.current_image == "icon.png"


async def test_cancel_request_schedules_the_sweep(monkeypatch):
    calls = capture_park(monkeypatch)
    pool = make_pool()
    bridge = make_bridge(pool)
    reply = tr.cancel_request(bridge)
    assert reply == {"ok": True, "scheduled": True}
    assert len(calls) == 1, "the sweep runs on its own task, not on the doomed batch"
    close_pending(calls)
    assert "Cancel" in log_text(bridge)


async def test_cancel_request_without_a_pool_does_nothing(monkeypatch):
    calls = capture_park(monkeypatch)
    assert tr.cancel_request(make_bridge(None)) == {"ok": True, "scheduled": False}
    assert calls == []


# ---- D-5: Clear time is a state reset, not a promise ------------------------

def test_clear_time_makes_a_cooling_tab_ready():
    pool = make_pool()
    bridge = make_bridge(pool)
    page = pool.get_page("a")
    page.status = PageStatus.COOLDOWN
    page.cooldown_until = time.time() + 900
    page.cooldown_total = 900
    info = tr.clear_time(bridge, "a")
    assert info["ok"] and 895 <= info["was"] <= 900 and info["busy"] is False
    assert page.remaining_seconds() == 0 and page.is_free()
    assert "ready now" in log_text(bridge)


def test_clear_time_repairs_a_stale_busy_tab():
    """RED at 71970e1: `{"ok": false, "error": "job still running…"}` — a dead end."""
    pool = make_pool()
    bridge = make_bridge(pool)
    page = stale_busy(pool)
    info = tr.clear_time(bridge, "a")
    assert info["ok"] and info["job_cleared"] is True and info["busy"] is False
    assert page.current_image is None and page.is_free()


def test_clear_time_never_lies_while_a_job_runs():
    pool = make_pool()
    bridge = make_bridge(pool, live=True)
    page = pool.get_page("a")
    page.status = PageStatus.WAITING_GENERATION
    page.current_image = "running.png"
    page.cooldown_until = time.time() + 120
    page.cooldown_total = 120
    info = tr.clear_time(bridge, "a")
    assert info["ok"] and info["busy"] is True and 115 <= info["was"] <= 120
    assert page.remaining_seconds() == 0
    assert page.current_image == "running.png", "the job keeps its page"
    assert "still running" in log_text(bridge)


def test_clear_time_is_idempotent():
    pool = make_pool()
    bridge = make_bridge(pool)
    assert tr.clear_time(bridge, "a")["was"] == 0
    second = tr.clear_time(bridge, "a")
    assert second["ok"] and second["was"] == 0 and pool.get_page("a").is_free()


def test_clear_time_on_an_unknown_tab_is_refused():
    bridge = make_bridge(make_pool())
    assert tr.clear_time(bridge, "ghost") == {"ok": False, "error": "unknown tab"}


def test_clear_time_without_a_pool_is_refused():
    bridge = make_bridge(None)
    assert tr.clear_time(bridge, "a") == {"ok": False, "error": "pool not initialized"}


# ---- the park is bounded, hides the overlay and never raises ---------------

async def test_a_raising_page_reset_still_parks(monkeypatch):
    calls = capture_park(monkeypatch)

    async def boom(ctx):
        raise RuntimeError("cdp gone")

    pool = make_pool()
    bridge = make_bridge(pool)
    page = stale_busy(pool)
    pool.register_client("a", object(), object())   # a tab with a socket to reset
    tr.stop_request(bridge, "a")
    await park_calls(calls, monkeypatch, reset=boom)
    assert page.status == PageStatus.COOLDOWN, "a page reset failure never blocks the park"
    assert "reset failed" in log_text(bridge)


async def test_hiding_the_overlay_is_best_effort(monkeypatch):
    """F-3: the waiting window must go, even when the controller raises."""
    async def ok(ctx):
        return True, "mock"

    class Ctl:
        def __init__(self):
            self.calls = 0

        async def hide_watcher_overlay(self):
            self.calls += 1
            raise RuntimeError("dead socket")

    monkeypatch.setattr(tr, "reset_to_new_chat", ok)
    pool = make_pool()
    bridge = make_bridge(pool)
    ctl = Ctl()
    pool.register_client("a", object(), ctl)
    stale_busy(pool)
    assert await tr.park_tab(bridge, "a", tr.STOP_REASON, BASE) is True
    assert ctl.calls == 1, "the park tries to remove the waiting window"
    assert pool.get_page("a").status == PageStatus.COOLDOWN


async def test_park_tab_on_an_unknown_tab_is_a_no_op(monkeypatch):
    async def ok(ctx):
        return True, "mock"

    monkeypatch.setattr(tr, "reset_to_new_chat", ok)
    bridge = make_bridge(make_pool())
    assert await tr.park_tab(bridge, "ghost", tr.STOP_REASON, BASE) is False
