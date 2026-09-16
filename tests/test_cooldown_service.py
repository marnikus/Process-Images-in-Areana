"""Tests for app/services/cooldown_service.py — real PagePool, fake bridge.

RULE 8: executes the real pool + service; only CDP/bridge boundary faked.
No real sleeps except one short expiry wait (<0.5s).
"""

import time
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.services import cooldown_service as svc


def make_info(tab_id):
    return PageInfo(ws_url=f"ws://{tab_id}", tab_id=tab_id, title=f"T-{tab_id}",
                     url="https://arena.ai", status=PageStatus.STEADY, is_connected=True)


def make_bridge(session=None, cancelled=False, paused=False):
    state = {"cooldown_enabled": True, "cooldown_min_seconds": 300,
             "cooldown_captcha_penalty_seconds": 900}
    if session:
        state.update(session)
    logs = []
    return SimpleNamespace(
        _cancel_requested=cancelled,
        _pause_requested=paused,
        config=SimpleNamespace(get_state=lambda k, d=None: state.get(k, d)),
        _log=lambda m, l="info": logs.append((m, l)),
        _emit_pool_status=lambda: logs.append(("emit", "")),
        _logs=logs,
        _session=state,
    )


@pytest.mark.unit
def test_start_cooldown_blocks_acquire_until_expiry():
    pool = PagePool()
    pool.add_page(make_info("a"))
    assert svc.start_cooldown(pool, "a", 300, reason="job done") is True
    page = pool.get_page("a")
    assert page.status == PageStatus.COOLDOWN
    assert page.is_free() is False
    assert page.remaining_seconds() > 0
    assert pool.get_counts() == (1, 0)
    snap = pool.status_snapshot()
    assert snap["cooling"] == 1
    assert snap["pages"][0]["cooldown_remaining"] > 0


@pytest.mark.unit
def test_zero_base_cooldown_goes_steady():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "job1")
    assert svc.start_cooldown(pool, "a", 0) is True
    assert pool.get_page("a").status == PageStatus.STEADY


@pytest.mark.unit
def test_start_cooldown_unknown_tab_fails_open():
    pool = PagePool()
    assert svc.start_cooldown(pool, "nope", 300) is False


@pytest.mark.unit
def test_refresh_expired_flips_only_expired():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    svc.start_cooldown(pool, "a", 300)
    svc.start_cooldown(pool, "b", 300)
    pool.get_page("a").cooldown_until = time.time() - 1  # force expiry
    expired = svc.refresh_expired(pool)
    assert expired == ["a"]
    assert pool.get_page("a").status == PageStatus.STEADY
    assert pool.get_page("a").is_free() is True
    assert pool.get_page("b").status == PageStatus.COOLDOWN


@pytest.mark.unit
def test_reset_cooldown_makes_steady_and_clears_pending():
    pool = PagePool()
    pool.add_page(make_info("a"))
    svc.add_captcha_penalty(pool, "a", 900)
    svc.start_cooldown(pool, "a", 300)
    assert svc.reset_cooldown(pool, "a") is True
    page = pool.get_page("a")
    assert page.status == PageStatus.STEADY
    assert page.pending_penalty == 0
    assert page.captcha_count == 1  # history kept for display
    assert svc.reset_cooldown(pool, "nope") is False


@pytest.mark.unit
def test_reset_never_frees_running_job():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "job1")
    svc.add_captcha_penalty(pool, "a", 900)
    assert svc.reset_cooldown(pool, "a") is True
    page = pool.get_page("a")
    assert page.status == PageStatus.BUSY  # untouched
    assert page.pending_penalty == 0  # only pending cleared


@pytest.mark.unit
def test_edit_cooldown_rules():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    pool.mark_busy("b", "job1")
    assert svc.edit_cooldown(pool, "b", 60) is False  # running job refused
    assert svc.edit_cooldown(pool, "nope", 60) is False
    assert svc.edit_cooldown(pool, "a", 120) is True  # parks steady tab
    assert pool.get_page("a").status == PageStatus.COOLDOWN
    assert pool.get_page("a").cooldown_reason == "manual"
    assert svc.edit_cooldown(pool, "a", 0) is True  # 0 = ready now
    assert pool.get_page("a").status == PageStatus.STEADY


@pytest.mark.unit
def test_captcha_penalty_stacks_and_is_per_tab():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    assert svc.add_captcha_penalty(pool, "a", 900) == 1
    assert svc.add_captcha_penalty(pool, "a", 900) == 2
    assert svc.add_captcha_penalty(pool, "nope", 900) == -1
    page_a = pool.get_page("a")
    assert page_a.pending_penalty == 1800  # stacked while idle
    assert pool.get_page("b").pending_penalty == 0  # tab B unaffected
    assert pool.get_page("b").captcha_count == 0
    svc.start_cooldown(pool, "a", 300)
    assert page_a.cooldown_total == 2100  # 300 base + 2x900
    assert page_a.pending_penalty == 0  # applied
    # penalty during active cooldown extends immediately
    before = page_a.cooldown_until
    assert svc.add_captcha_penalty(pool, "a", 900) == 3
    assert page_a.cooldown_until == before + 900
    assert page_a.cooldown_total == 3000


@pytest.mark.unit
def test_longest_remaining_and_aware_timeout():
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    assert svc.longest_remaining(pool) == 0
    assert svc.cooldown_aware_timeout(pool) == 600.0
    svc.start_cooldown(pool, "a", 300)
    assert 0 < svc.longest_remaining(pool) <= 300
    svc.edit_cooldown(pool, "b", 3600)
    assert svc.cooldown_aware_timeout(pool) > 3600
    assert svc.remaining_for(pool, "nope") == -1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_ready_fast_paths():
    pool = PagePool()
    pool.add_page(make_info("a"))
    bridge = make_bridge()
    assert await svc.wait_for_tab_ready(pool, "a", bridge) is True
    assert await svc.wait_for_tab_ready(pool, "unknown", bridge) is True
    pool.mark_busy("a", "job1")
    cancelled = make_bridge(cancelled=True)
    assert await svc.wait_for_tab_ready(pool, "a", cancelled) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_ready_waits_for_expiry(monkeypatch):
    monkeypatch.setattr(svc, "_POLL_SEC", 0.01)
    pool = PagePool()
    pool.add_page(make_info("a"))
    svc.start_cooldown(pool, "a", 300)
    pool.get_page("a").cooldown_until = time.time() + 1.2
    bridge = make_bridge()
    assert await svc.wait_for_tab_ready(pool, "a", bridge) is True
    assert pool.get_page("a").status == PageStatus.STEADY
    assert any("cooling" in m for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finish_normal_starts_cooldown(monkeypatch):
    calls = []

    async def fake_reset(ctx):
        calls.append(ctx)
        return True, "mock ready"

    monkeypatch.setattr(svc, "reset_to_new_chat", fake_reset)
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "job1")
    bridge = make_bridge()
    ctx = svc.FinishCtx(pool=pool, bridge=bridge, tab_id="a", ctrl=object(), client=object())
    assert await svc.finish_page_after_job(ctx) is True
    assert len(calls) == 1
    page = pool.get_page("a")
    assert page.status == PageStatus.COOLDOWN
    assert page.cooldown_total == 300


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finish_disabled_or_cancelled_goes_steady(monkeypatch):
    async def fake_reset(ctx):
        return True, "mock ready"

    monkeypatch.setattr(svc, "reset_to_new_chat", fake_reset)
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.add_page(make_info("b"))
    pool.mark_busy("a", "job1")
    pool.mark_busy("b", "job2")
    disabled = make_bridge(session={"cooldown_enabled": False})
    ctx_a = svc.FinishCtx(pool=pool, bridge=disabled, tab_id="a", ctrl=object(), client=object())
    assert await svc.finish_page_after_job(ctx_a) is True
    assert pool.get_page("a").status == PageStatus.STEADY
    cancelled = make_bridge(cancelled=True)
    ctx_b = svc.FinishCtx(pool=pool, bridge=cancelled, tab_id="b", ctrl=object(), client=object())
    assert await svc.finish_page_after_job(ctx_b) is True
    assert pool.get_page("b").status == PageStatus.STEADY  # no cooldown after cancel


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finish_failed_reset_still_cools(monkeypatch):
    async def fake_reset(ctx):
        return False, "boom"

    monkeypatch.setattr(svc, "reset_to_new_chat", fake_reset)
    pool = PagePool()
    pool.add_page(make_info("a"))
    pool.mark_busy("a", "job1")
    bridge = make_bridge()
    ctx = svc.FinishCtx(pool=pool, bridge=bridge, tab_id="a", ctrl=object(), client=object())
    assert await svc.finish_page_after_job(ctx) is True
    assert pool.get_page("a").status == PageStatus.COOLDOWN
    assert any("boom" in m for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finish_unknown_tab_returns_false(monkeypatch):
    async def fake_reset(ctx):
        return True, "mock ready"

    monkeypatch.setattr(svc, "reset_to_new_chat", fake_reset)
    pool = PagePool()
    bridge = make_bridge()
    ctx = svc.FinishCtx(pool=pool, bridge=bridge, tab_id="nope", ctrl=object(), client=object())
    assert await svc.finish_page_after_job(ctx) is False


@pytest.mark.unit
def test_ensure_registers_missing_primary_tab():
    pool = PagePool()
    info = PageInfo(tab_id="tab1", ws_url="ws://x", title="Arena", url="https://arena.ai/abc")
    assert svc.ensure_pool_page(pool, info) is True
    page = pool.get_page("tab1")
    assert page.status == PageStatus.STEADY
    assert page.is_connected is True
    assert (page.title, page.url) == ("Arena", "https://arena.ai/abc")
    # finish now cools instead of unknown-tab no-op
    assert svc.start_cooldown(pool, "tab1", 300, reason="job done") is True
    assert pool.get_page("tab1").status == PageStatus.COOLDOWN


@pytest.mark.unit
def test_ensure_fills_empty_url_title_only():
    pool = PagePool()
    pool.add_page(PageInfo(tab_id="t", ws_url="ws://t", title="", url=""))
    assert svc.ensure_pool_page(pool, PageInfo(tab_id="t", title="Live", url="https://x.ai/y")) is True
    page = pool.get_page("t")
    assert (page.title, page.url) == ("Live", "https://x.ai/y")
    assert svc.ensure_pool_page(pool, PageInfo(tab_id="t", title="Other", url="https://other/")) is True
    assert (page.title, page.url) == ("Live", "https://x.ai/y")


@pytest.mark.unit
def test_ensure_rejects_missing_pool_or_tab():
    assert svc.ensure_pool_page(None, PageInfo(tab_id="t")) is False
    assert svc.ensure_pool_page(PagePool(), PageInfo(tab_id="")) is False


@pytest.mark.unit
def test_resolve_primary_tab_adopts_single_page():
    pool = PagePool()
    pool.add_page(make_info("only"))
    assert svc.resolve_primary_tab(pool, "") == "only"
    assert svc.resolve_primary_tab(pool, "only") == "only"
    assert svc.resolve_primary_tab(pool, "ghost") == "ghost"
    pool.add_page(make_info("second"))
    assert svc.resolve_primary_tab(pool, "") == ""


@pytest.mark.unit
def test_resolve_primary_tab_no_pool():
    assert svc.resolve_primary_tab(None, "") == ""
    assert svc.resolve_primary_tab(None, "x") == "x"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_batch_ready_immediate_when_ready():
    pool = PagePool()
    pool.add_page(make_info("a"))
    bridge = make_bridge()
    assert await svc.wait_for_batch_ready(pool, ["a"], bridge) is True
    assert await svc.wait_for_batch_ready(pool, [], bridge) is True
    assert await svc.wait_for_batch_ready(pool, [""], bridge) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_batch_ready_waits_for_zero(monkeypatch):
    monkeypatch.setattr(svc, "_POLL_SEC", 0.01)
    pool = PagePool()
    pool.add_page(make_info("a"))
    svc.start_cooldown(pool, "a", 2, reason="job done")
    bridge = make_bridge()
    started = time.monotonic()
    assert await svc.wait_for_batch_ready(pool, ["a"], bridge) is True
    assert time.monotonic() - started >= 0.5
    assert pool.get_page("a").status == PageStatus.STEADY
    assert any("00" in m or "cooldown" in m.lower() for m, _ in bridge._logs)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_batch_ready_cancel_returns_false(monkeypatch):
    monkeypatch.setattr(svc, "_POLL_SEC", 0.01)
    pool = PagePool()
    pool.add_page(make_info("a"))
    svc.start_cooldown(pool, "a", 300, reason="job done")
    bridge = make_bridge(cancelled=True)
    assert await svc.wait_for_batch_ready(pool, ["a"], bridge) is False


@pytest.mark.unit
def test_register_job_done_increments():
    pool = PagePool()
    pool.add_page(make_info("a"))
    assert svc.register_job_done(pool, "a") == 1
    assert svc.register_job_done(pool, "a") == 2
    assert pool.get_page("a").jobs_completed == 2


@pytest.mark.unit
def test_register_job_done_unknown():
    assert svc.register_job_done(PagePool(), "nope") == -1
    assert svc.register_job_done(None, "a") == -1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finish_increments_job_counter(monkeypatch):
    async def fake_reset(ctx):
        return True, "mock ready"

    monkeypatch.setattr(svc, "reset_to_new_chat", fake_reset)
    pool = PagePool()
    pool.add_page(make_info("a"))
    bridge = make_bridge()
    ctx = svc.FinishCtx(pool=pool, bridge=bridge, tab_id="a", ctrl=object(), client=object())
    assert await svc.finish_page_after_job(ctx) is True
    assert pool.get_page("a").jobs_completed == 1


@pytest.mark.unit
def test_restore_page_stats_max_and_missing():
    from app.persistence.cooldown_store import normalize_url
    pool = PagePool()
    pool.add_page(make_info("a"))
    norm = normalize_url("https://arena.ai")
    stats = {norm: {"jobs_completed": 7}}
    assert svc.restore_page_stats(pool, "a", norm, stats) == 7
    pool.get_page("a").jobs_completed = 9
    assert svc.restore_page_stats(pool, "a", norm, stats) == 9  # max, idempotent
    assert svc.restore_page_stats(pool, "nope", norm, stats) == -1
    assert svc.restore_page_stats(pool, "a", norm, {}) == 9  # nothing saved: keep live
