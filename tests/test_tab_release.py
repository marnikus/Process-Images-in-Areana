"""Stop & Cancel actually release the tab — the reported bug, one per symptom.

RULE 8: drives the real `tab_release` pipeline against a real `PagePool` with
only the CDP boundary faked, so every test here fails if the feature is
deleted. The bug report's five items are the five sections below.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import cooldown_service as svc
from app.services import tab_release as tr

pytestmark = pytest.mark.unit


def make_info(tab_id="t1"):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url="https://arena.ai", status=PageStatus.STEADY, is_connected=True)


def make_bridge(**over):
    state = {"cooldown_enabled": True, "cooldown_min_seconds": 300,
             "cooldown_captcha_penalty_seconds": 900}
    state.update(over.pop("session", {}))
    logs = []
    return SimpleNamespace(
        _cancel_requested=over.pop("cancelled", False),
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        _logs=logs,
        **over,
    )


class FakeCtrl:
    """Records the page-side mechanics the release must reuse."""

    def __init__(self, fail=False):
        self.hidden = 0
        self.fail = fail

    async def hide_watcher_overlay(self):
        if self.fail:
            raise RuntimeError("cdp down")
        self.hidden += 1
        return True


def busy_pool(tab_id="t1", image="a.png"):
    """A pool whose tab is mid-job — exactly the state Stop/Cancel must clear."""
    pool = PagePool()
    pool.add_page(make_info(tab_id))
    pool.mark_busy(tab_id, "job-1")
    svc.set_tab_image(pool, tab_id, image)
    return pool


def release(pool, bridge, tab_id="t1", ctrl=None, reason="stopped by user"):
    ctx = tr.ReleaseCtx(pool=pool, bridge=bridge, tab_id=tab_id,
                        ctrl=ctrl or FakeCtrl(), reason=reason)
    return asyncio.run(tr.release_tab(ctx))


# ── 1. the row must stop showing a processing image ──────────────────────────

def test_release_clears_the_processing_image_from_the_row():
    pool, bridge = busy_pool(), make_bridge()
    assert pool.get_page("t1").current_image == "a.png"  # the reported symptom
    assert release(pool, bridge) is True
    assert pool.get_page("t1").current_image is None


def test_release_hides_the_waiting_window():
    """'remove waiting win' — the overlay mechanic that already existed."""
    pool, bridge, ctrl = busy_pool(), make_bridge(), FakeCtrl()
    release(pool, bridge, ctrl=ctrl)
    assert ctrl.hidden == 1


def test_release_resets_the_page_to_a_new_chat(monkeypatch):
    """'Set web page to new chat status' — reusing the existing mechanic."""
    seen = {}

    async def _fake_reset(ctx):
        seen["cancel_check"] = ctx.cancel_check
        return True, "new chat ready"

    monkeypatch.setattr(tr, "reset_to_new_chat", _fake_reset)
    release(busy_pool(), make_bridge())
    assert "cancel_check" in seen, "the new-chat reset must run"
    # The release runs *because* the user cancelled, so it must not
    # abort on the cancel flag — that was the original no-op bug.
    assert seen["cancel_check"] is None


# ── 2. status must become a cooldown that is actually elapsing ───────────────

def test_release_sets_cooldown_with_time_left():
    pool, bridge = busy_pool(), make_bridge()
    release(pool, bridge)
    page = pool.get_page("t1")
    assert page.status == PageStatus.COOLDOWN
    assert page.remaining_seconds() > 0, "cooldown must elapse, not sit at 0"
    assert page.is_free() is False


def test_release_adds_the_configured_penalty_on_top_of_the_base():
    """Default 5 min base + the user-configured penalty (one control, RULE 10)."""
    pool, bridge = busy_pool(), make_bridge(session={"cooldown_min_seconds": 300})
    release(pool, bridge)
    assert pool.get_page("t1").cooldown_total == 300 + tr.STOP_PENALTY_SECONDS


def test_the_penalty_is_user_configurable():
    pool = busy_pool()
    bridge = make_bridge(session={"cooldown_min_seconds": 60,
                                  "cooldown_stop_penalty_seconds": 120})
    release(pool, bridge)
    assert pool.get_page("t1").cooldown_total == 180


def test_cooldown_disabled_still_releases_the_tab_but_arms_no_timer():
    """RULE 4: 'no pause configured' is empty, not broken — the tab still frees."""
    pool = busy_pool()
    bridge = make_bridge(session={"cooldown_enabled": False})
    assert release(pool, bridge) is True
    page = pool.get_page("t1")
    assert page.current_image is None
    assert page.status == PageStatus.STEADY
    assert page.remaining_seconds() == 0


# ── 3. the stop request is consumed, so the button stops being a no-op ───────

def test_release_consumes_the_abort_flag():
    pool, bridge = busy_pool(), make_bridge()
    svc.request_tab_abort(pool, "t1")
    assert svc.is_tab_aborted(pool, "t1") is True
    release(pool, bridge)
    assert svc.is_tab_aborted(pool, "t1") is False, "a honoured stop must not linger"


def test_release_reports_every_step(monkeypatch):
    """RULE 2: the reported bug was silence after 'Stop requested'."""
    async def _ok(_ctx):
        return True, "new chat ready"

    monkeypatch.setattr(tr, "reset_to_new_chat", _ok)
    pool, bridge = busy_pool(), make_bridge()
    release(pool, bridge)
    text = " ".join(m for m, _ in bridge._logs)
    assert "released" in text.lower()
    assert "cooling" in text.lower()


def test_release_emits_pool_status_so_the_ui_repaints():
    pool, bridge = busy_pool(), make_bridge()
    release(pool, bridge)
    assert ("emit", "") in bridge._logs


# ── 4. failure tolerance — a dead page must never strand the tab ─────────────

def test_a_failing_overlay_hide_still_releases_the_tab():
    pool, bridge = busy_pool(), make_bridge()
    assert release(pool, bridge, ctrl=FakeCtrl(fail=True)) is True
    assert pool.get_page("t1").current_image is None
    assert pool.get_page("t1").remaining_seconds() > 0


def test_a_failing_new_chat_reset_still_cools_the_tab(monkeypatch):
    async def _boom(_ctx):
        raise RuntimeError("page gone")

    monkeypatch.setattr(tr, "reset_to_new_chat", _boom)
    pool, bridge = busy_pool(), make_bridge()
    assert release(pool, bridge) is True
    assert pool.get_page("t1").remaining_seconds() > 0
    assert any("reset failed" in m.lower() for m, _ in bridge._logs)


def test_a_missing_ctrl_is_not_fatal():
    pool, bridge = busy_pool(), make_bridge()
    ctx = tr.ReleaseCtx(pool=pool, bridge=bridge, tab_id="t1", ctrl=None, reason="x")
    assert asyncio.run(tr.release_tab(ctx)) is True
    assert pool.get_page("t1").current_image is None


def test_an_unknown_tab_reports_false_instead_of_raising():
    pool, bridge = busy_pool(), make_bridge()
    ctx = tr.ReleaseCtx(pool=pool, bridge=bridge, tab_id="ghost", ctrl=FakeCtrl(),
                        reason="x")
    assert asyncio.run(tr.release_tab(ctx)) is False


# ── 5. Cancel releases every active tab (the whole cycle) ────────────────────

def test_cancel_releases_every_tab_that_holds_an_image(monkeypatch):
    async def _ok(_ctx):
        return True, "new chat ready"

    monkeypatch.setattr(tr, "reset_to_new_chat", _ok)
    pool = PagePool()
    for tid in ("t1", "t2", "t3"):
        pool.add_page(make_info(tid))
    for tid in ("t1", "t2"):
        pool.mark_busy(tid, f"job-{tid}")
        svc.set_tab_image(pool, tid, "a.png")
    bridge = make_bridge(_page_pool=pool)

    assert asyncio.run(tr.release_active_tabs(bridge, reason="cancelled")) == 2
    for tid in ("t1", "t2"):
        assert pool.get_page(tid).current_image is None
        assert pool.get_page(tid).remaining_seconds() > 0
    # an idle tab is untouched — cancel penalises the tabs that were working
    assert pool.get_page("t3").remaining_seconds() == 0


def test_releasing_with_no_pool_is_a_no_op():
    assert asyncio.run(tr.release_active_tabs(make_bridge(_page_pool=None))) == 0


def test_release_active_tabs_survives_a_hostile_pool():
    class Hostile:
        def status_snapshot(self):
            raise RuntimeError("pool gone")

    assert asyncio.run(tr.release_active_tabs(make_bridge(_page_pool=Hostile()))) == 0


# ── 6. an idle tab is empty, not broken (RULE 4) ─────────────────────────────

def test_an_idle_steady_tab_is_not_releasable():
    """Stop on a resting worker must not hand it a penalty it never earned."""
    pool = PagePool()
    pool.add_page(make_info("t1"))
    assert tr.tab_needs_release(pool, "t1") is False
    assert tr.start_tab_release(make_bridge(_page_pool=pool), "t1") is False
    assert pool.get_page("t1").remaining_seconds() == 0


def test_a_tab_with_an_image_or_a_busy_status_is_releasable():
    pool = busy_pool()
    assert tr.tab_needs_release(pool, "t1") is True
    svc.set_tab_image(pool, "t1", None)      # image cleared, status still busy
    assert tr.tab_needs_release(pool, "t1") is True


def test_needs_release_is_false_for_unknown_tabs_and_dead_pools():
    assert tr.tab_needs_release(PagePool(), "ghost") is False
    assert tr.tab_needs_release(None, "t1") is False


# ── 7. the Qt-slot seam schedules instead of blocking ────────────────────────

def test_start_tab_release_schedules_the_pipeline(monkeypatch):
    captured = {}

    def _fake_schedule(bridge, coro):
        captured["scheduled"] = True
        coro.close()          # we assert on scheduling, not on completion
        return object()

    monkeypatch.setattr("app.services.run_state.schedule_coro", _fake_schedule)
    pool = busy_pool()
    assert tr.start_tab_release(make_bridge(_page_pool=pool), "t1") is True
    assert captured.get("scheduled") is True


def test_cancel_sweep_snapshots_the_working_set_before_scheduling(monkeypatch):
    """The killed task clears current_image in its finally — deciding the list
    later would race that cleanup and release nothing."""
    seen = {}

    def _fake_schedule(bridge, coro):
        seen["coro"] = coro
        return object()

    monkeypatch.setattr("app.services.run_state.schedule_coro", _fake_schedule)
    pool = busy_pool()
    bridge = make_bridge(_page_pool=pool)
    assert tr.start_release_active_tabs(bridge) is True
    svc.set_tab_image(pool, "t1", None)       # the race: cleanup lands first
    assert asyncio.run(seen["coro"]) == 1, "snapshotted tab is still released"


def test_the_sweep_does_not_schedule_when_no_tab_is_working():
    pool = PagePool()
    pool.add_page(make_info("t1"))
    assert tr.start_release_active_tabs(make_bridge(_page_pool=pool)) is False


def test_scheduling_failures_are_reported_not_raised(monkeypatch):
    def _boom(_bridge, coro):
        coro.close()
        raise RuntimeError("no loop")

    monkeypatch.setattr("app.services.run_state.schedule_coro", _boom)
    bridge = make_bridge(_page_pool=busy_pool())
    assert tr.start_tab_release(bridge, "t1") is False
    assert tr.start_release_active_tabs(bridge) is False
    assert any("could not start" in m.lower() for m, _ in bridge._logs)


# ── 8. hostile surroundings — the release must still not raise (RULE 4) ──────

class Hostile:
    """A bridge/pool whose every attribute access explodes."""

    def __getattr__(self, name):
        raise RuntimeError("hostile")


def test_every_reporting_helper_survives_a_hostile_bridge():
    tr._log(Hostile(), "x")                                  # dead logger
    tr._emit(Hostile())                                      # dead emit
    assert tr.penalty_seconds(Hostile()) == tr.STOP_PENALTY_SECONDS
    assert tr.penalty_seconds(SimpleNamespace(config=None)) == tr.STOP_PENALTY_SECONDS


def test_the_label_falls_back_to_the_short_id_when_the_pool_is_hostile():
    ctx = tr.ReleaseCtx(pool=Hostile(), bridge=make_bridge(), tab_id="abcdefghijklmno")
    assert tr._label(ctx) == "abcdefghijkl"


def test_a_bad_penalty_setting_falls_back_to_the_default():
    bridge = make_bridge(session={"cooldown_stop_penalty_seconds": "not a number"})
    assert tr.penalty_seconds(bridge) == tr.STOP_PENALTY_SECONDS


def test_settle_steady_and_ctrl_lookup_tolerate_a_hostile_pool():
    tr._settle_steady(tr.ReleaseCtx(pool=Hostile(), bridge=make_bridge(), tab_id="t1"))
    assert tr._ctrl_for(Hostile(), "t1") is None
    assert tr._active_tab_ids(Hostile()) == []


def test_needs_release_survives_a_hostile_pool():
    assert tr.tab_needs_release(Hostile(), "t1") is False


def test_release_tab_reports_false_for_a_hostile_pool():
    ctx = tr.ReleaseCtx(pool=Hostile(), bridge=make_bridge(), tab_id="t1")
    assert asyncio.run(tr.release_tab(ctx)) is False


def test_a_raising_release_inside_the_sweep_is_logged_not_fatal(monkeypatch):
    """One bad tab must never abort the release of the others."""
    async def _boom(_ctx):
        raise RuntimeError("tab exploded")

    monkeypatch.setattr(tr, "release_tab", _boom)
    bridge = make_bridge(_page_pool=busy_pool())
    assert asyncio.run(tr.release_tabs(bridge, ["t1"])) == 0
    assert any("release failed" in m.lower() for m, _ in bridge._logs)


def test_release_tabs_with_no_pool_or_no_ids_is_a_no_op():
    assert asyncio.run(tr.release_tabs(make_bridge(_page_pool=None), ["t1"])) == 0
    assert asyncio.run(tr.release_tabs(make_bridge(_page_pool=busy_pool()), None)) == 0


def test_a_zero_base_and_zero_penalty_still_frees_the_tab():
    """Both knobs at zero: nothing to cool, so the tab must go ready (RULE 4)."""
    pool = busy_pool()
    bridge = make_bridge(session={"cooldown_min_seconds": 0,
                                  "cooldown_stop_penalty_seconds": 0})
    assert release(pool, bridge) is True
    page = pool.get_page("t1")
    assert page.status == PageStatus.STEADY
    assert page.remaining_seconds() == 0


def test_the_label_survives_an_unimportable_pool_module(monkeypatch):
    """The import guard is real: the release still names the tab if it dies."""
    import sys
    monkeypatch.setitem(sys.modules, "app.browser.page_pool", None)
    ctx = tr.ReleaseCtx(pool=busy_pool(), bridge=make_bridge(), tab_id="abcdefghijklmno")
    assert tr._label(ctx) == "abcdefghijkl"
