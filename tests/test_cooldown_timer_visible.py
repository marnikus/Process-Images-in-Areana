"""The countdown never hides — seam/integration suite (RED-first).

User report: "the timer shows only + 15:00, not real time elapsing; it hides
after Cancel current run and does not come back although the cooldown is still
active — never hide it: whenever time is elapsing, show it (00:00 when ready)".

These tests drive the REAL `PagePool` + `cooldown_service` (RULE 8) and read the
exact snapshot the UI renders, so a green run means the value the JS receives
really is a live countdown, not a status string that happens to look like one.
"""

import time
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.tab_alias import AliasBook
from app.services import cooldown_service as svc

pytestmark = pytest.mark.integration

PENALTY = 900
BASE = 300


def make_info(tab_id="a"):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                    url="https://arena.ai/", status=PageStatus.STEADY, is_connected=True)


def make_bridge(session=None, cancelled=False):
    state = {"cooldown_enabled": True, "cooldown_min_seconds": BASE,
             "cooldown_captcha_penalty_seconds": PENALTY,
             "cooldown_rate_limit_penalty_seconds": 1800}
    if session:
        state.update(session)
    logs = []
    return SimpleNamespace(
        _cancel_requested=cancelled,
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        _logs=logs,
        _session=state,
    )


def make_pool(*tab_ids, book=None):
    pool = PagePool(alias_book=book)
    for tab_id in tab_ids or ("a",):
        pool.add_page(make_info(tab_id))
    return pool


def snap_page(pool, tab_id="a"):
    return next(p for p in pool.status_snapshot()["pages"] if p["tab_id"] == tab_id)


def log_text(bridge):
    return " | ".join(m for m, _lvl in bridge._logs)


async def finish(pool, bridge, tab_id="a", cancelled=False, monkeypatch=None):
    async def fake_reset(ctx):
        return True, "mock ready"
    monkeypatch.setattr(svc, "reset_to_new_chat", fake_reset)
    ctx = svc.FinishCtx(pool=pool, bridge=bridge, tab_id=tab_id, ctrl=object(), client=object())
    return await svc.finish_page_after_job(ctx)


# ---- D-2: a penalty is a live timer, never a hidden number ------------------

def test_a_penalty_on_a_resting_tab_starts_a_live_timer():
    """RED at 8db8ec6: `+15:00 pending`, status steady, `cooldown_remaining == 0`."""
    pool = make_pool("a")
    svc.note_captcha_event(pool, "a", make_bridge())
    page = pool.get_page("a")
    assert page.status == PageStatus.COOLDOWN
    assert page.pending_penalty == 0
    assert page.is_cooling() is True
    assert 880 <= page.remaining_seconds() <= PENALTY
    assert page.cooldown_total == PENALTY
    snap = snap_page(pool)
    assert snap["cooldown_remaining"] > 0
    assert pool.status_snapshot()["cooling"] == 1
    assert page.is_free() is False                # the timer gates the dispatch


@pytest.mark.asyncio
async def test_a_penalty_on_a_busy_tab_is_a_debt_until_the_job_ends(monkeypatch):
    pool = make_pool("a")
    pool.mark_busy("a", "job1")
    svc.note_captcha_event(pool, "a", make_bridge())
    page = pool.get_page("a")
    assert (page.status, page.pending_penalty) == (PageStatus.BUSY, PENALTY)   # unchanged
    assert page.remaining_seconds() == 0          # nothing is elapsing yet
    assert snap_page(pool)["pending_penalty"] == PENALTY   # and the UI can say so
    assert await finish(pool, make_bridge(), monkeypatch=monkeypatch) is True
    page = pool.get_page("a")
    assert page.pending_penalty == 0
    assert page.is_cooling() is True
    assert page.remaining_seconds() > BASE        # base + the debt, one live timer
    assert snap_page(pool)["cooldown_remaining"] > BASE


def test_a_penalty_on_a_cooling_tab_extends_the_live_timer():
    pool = make_pool("a")
    svc.start_cooldown(pool, "a", BASE)
    svc.note_captcha_event(pool, "a", make_bridge())
    page = pool.get_page("a")
    assert page.cooldown_total == BASE + PENALTY
    assert page.remaining_seconds() > BASE + PENALTY - 20


def test_a_penalty_on_a_resting_tab_blocks_the_next_dispatch():
    """A resting tab with a debt + a new penalty cools for both, never dropping the debt."""
    pool = make_pool("a")
    pool.mark_busy("a", "job1")
    svc.add_captcha_penalty(pool, "a", PENALTY)   # debt: the job is running
    pool.mark_steady("a")                         # job over, debt still owed
    svc.add_captcha_penalty(pool, "a", 60)        # resting now: both cool as one timer
    page = pool.get_page("a")
    assert page.pending_penalty == 0
    assert page.is_cooling() is True
    assert page.remaining_seconds() > PENALTY - 20
    assert pool.get_counts() == (1, 0)


# ---- D-3: no settle path may strand a debt ---------------------------------

@pytest.mark.asyncio
async def test_cancel_with_a_stacked_debt_leaves_a_visible_countdown(monkeypatch):
    """RED at 8db8ec6: Cancel settled STEADY and left `+15:00 pending` forever."""
    pool = make_pool("a")
    bridge = make_bridge(cancelled=True)
    pool.mark_busy("a", "job1")
    svc.note_captcha_event(pool, "a", bridge)
    assert await finish(pool, bridge, monkeypatch=monkeypatch) is True
    page = pool.get_page("a")
    assert page.status == PageStatus.COOLDOWN
    assert page.pending_penalty == 0
    assert page.remaining_seconds() > 0
    assert page.is_free() is False
    assert snap_page(pool)["cooldown_remaining"] > 0
    assert "penalty" in log_text(bridge).lower() and "cooling" in log_text(bridge).lower()


@pytest.mark.asyncio
async def test_cancel_without_a_debt_still_goes_steady_at_once(monkeypatch):
    pool = make_pool("a")
    bridge = make_bridge(cancelled=True)
    pool.mark_busy("a", "job1")
    assert await finish(pool, bridge, monkeypatch=monkeypatch) is True
    page = pool.get_page("a")
    assert page.status == PageStatus.STEADY and page.is_free() is True
    assert page.remaining_seconds() == 0


@pytest.mark.asyncio
async def test_cooldown_off_finish_materialises_the_debt(monkeypatch):
    """RED at 8db8ec6: 'cooldown off' skipped the debt too -> ready with 15 min owed."""
    pool = make_pool("a")
    bridge = make_bridge(session={"cooldown_enabled": False})
    pool.mark_busy("a", "job1")
    svc.note_captcha_event(pool, "a", bridge)
    assert await finish(pool, bridge, monkeypatch=monkeypatch) is True
    page = pool.get_page("a")
    assert page.status == PageStatus.COOLDOWN and page.is_cooling() is True
    assert 880 <= page.remaining_seconds() <= PENALTY
    assert snap_page(pool)["cooldown_remaining"] > 0


def test_reset_clears_a_resting_timer_and_debt_but_never_a_running_job():
    pool = make_pool("a", "b")
    svc.note_captcha_event(pool, "a", make_bridge())         # live timer on a resting tab
    assert svc.reset_cooldown(pool, "a") is True
    page = pool.get_page("a")
    assert (page.status, page.pending_penalty, page.is_free()) == (PageStatus.STEADY, 0, True)
    pool.mark_busy("b", "job1")
    svc.note_captcha_event(pool, "b", make_bridge())
    assert svc.reset_cooldown(pool, "b") is True
    busy = pool.get_page("b")
    assert busy.status == PageStatus.BUSY and busy.pending_penalty == PENALTY   # I-27


# ---- D-1: the timer is the authority ---------------------------------------

def test_start_cooldown_never_shortens_a_live_timer():
    """RED at 8db8ec6: `until = now + total` overwrote a longer pause."""
    pool = make_pool("a")
    svc.start_cooldown(pool, "a", 600)
    svc.start_cooldown(pool, "a", BASE)
    page = pool.get_page("a")
    assert page.remaining_seconds() > 580
    assert page.cooldown_total >= 600


def test_a_live_timer_keeps_gating_a_page_whose_status_was_clobbered():
    """RED at 8db8ec6 (the reported Cancel path): status steady, timer live, `is_free() True`."""
    pool = make_pool("a")
    svc.start_cooldown(pool, "a", PENALTY)
    pool.mark_steady("a")                      # exactly what _settle_pool_steady calls
    page = pool.get_page("a")
    assert page.status == PageStatus.STEADY
    assert page.remaining_seconds() > 0
    assert page.is_free() is False             # nothing may dispatch into a live timer
    snap = snap_page(pool)
    assert snap["cooldown_remaining"] > 0 and pool.status_snapshot()["cooling"] == 1


def test_try_expire_never_voids_a_live_timer_and_clears_residue_when_it_ended():
    pool = make_pool("a")
    page = pool.get_page("a")
    page.cooldown_until = time.time() + 60
    assert page.try_expire() is False
    assert page.remaining_seconds() > 0
    assert page.is_free() is False
    page.cooldown_until = time.time() - 1
    assert page.is_cooling() is False
    assert page.is_free() is True
    assert page.try_expire() is False          # already steady: not a "freed" flip
    assert page.cooldown_until == 0            # residue gone, not left behind
    svc.start_cooldown(pool, "a", BASE)
    assert pool.get_page("a").try_expire() is False
    pool.get_page("a").cooldown_until = time.time() - 1
    assert pool.get_page("a").try_expire() is True
    assert pool.get_page("a").cooldown_until == 0


def test_remaining_seconds_reads_the_clock_not_the_status():
    page = make_info()
    page.cooldown_until = time.time() + 120
    for status in (PageStatus.STEADY, PageStatus.BUSY, PageStatus.ERROR,
                   PageStatus.WAITING_CAPTCHA, PageStatus.COOLDOWN):
        page.status = status
        assert 110 <= page.remaining_seconds() <= 120, status
    page.cooldown_until = time.time() - 5
    assert page.remaining_seconds() == 0


# ---- the user's scenario, end to end (label + countdown in one snapshot) ----

@pytest.mark.asyncio
async def test_the_reported_scenario_shows_a_ticking_labeled_countdown(monkeypatch):
    """Cancel after a captcha: the snapshot the UI renders carries both the
    readable tab id and a live remaining value (RED at 8db8ec6: `aka_…` absent
    and `cooldown_remaining == 0`)."""
    book = AliasBook({"aaaa1111": {"no": 1, "email": "zeusthunder1991@gmail.com"}})
    pool = make_pool("aaaa1111", book=book)
    bridge = make_bridge(cancelled=True)
    pool.mark_busy("aaaa1111", "job1")
    svc.note_captcha_event(pool, "aaaa1111", bridge)
    assert await finish(pool, bridge, tab_id="aaaa1111", monkeypatch=monkeypatch) is True
    page = snap_page(pool, "aaaa1111")
    assert page["tab_label"] == "zeusthunder1991@gmail.com_0001"
    assert page["status"] == "cooldown"
    assert page["cooldown_remaining"] > 0
    assert page["pending_penalty"] == 0
    assert "zeusthunder1991@gmail.com_0001" in log_text(bridge)
