"""Dispatch lanes — the browser fork points (design D-8/D-9).

Parallel feeder (dispatcher), sequential lane (batch), the supervisor's reason
ladder and the cooldown finish: a Firefox pool page runs through the macro
lane with no CDP transport anywhere — honest success text, no phantom
"New-chat reset failed" warnings, no reconnect moves, and `cdp down` stops
being a wait when a free Firefox worker exists.
"""

import json
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool, discovered_page_info
from app.browser.uivision.discovery import FirefoxTab
from app.core.models import UrlRow
from app.services import cooldown_service as cds
from app.services import multi_page_dispatcher as mpd
from app.services.batch_orchestrator import BatchCtx, ImageResult, _emit_job_finished, _execute_firefox, _finish_primary_tab, _move_to_tab
from tests.characterization.harness import CORE_STACK, build_bridge, build_stack

pytestmark = pytest.mark.unit

FF_ID = "9THrgpBc.Profile1_tab0"


def ff_pool():
    pool = PagePool()
    tab = FirefoxTab(id=FF_ID, url="https://arena.ai/c/9", title="Arena",
                     profile_dir="/profiles/9THrgpBc.Profile1", profile_name="Profile1")
    pool.add_page(discovered_page_info(tab))
    return pool


def image():
    return SimpleNamespace(status="pending", error="", output_path="/tmp/out.png",
                           relative_path="pic.png", absolute_path="/tmp/pic.png",
                           assigned_url_id=None, attempt_count=0)


def env_with(tmp_path, pool=None):
    env = build_bridge(tmp_path, build_stack(CORE_STACK), n_images=1, tab_ids=[])
    env.bridge._page_pool = pool if pool is not None else PagePool()
    return env


def finished_messages(env):
    return [json.loads(p).get("message", "") for _job, p in env.recs["job_finished"].calls]


def log_lines(env):
    return [m for m, _lvl in env.recs["arena_log"].calls]


# ── the parallel feeder ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_firefox_claim_runs_the_macro_lane_and_reports_honestly(tmp_path, monkeypatch):
    env = env_with(tmp_path, ff_pool())
    page = env.bridge._page_pool.get_page(FF_ID)
    owner = UrlRow.create("https://arena.ai/c/9", tab_id=FF_ID)
    called = []

    async def run_macro_job(bridge, pool, tab_id):
        called.append(tab_id)
        return False, ""
    monkeypatch.setattr(mpd.firefox_job, "run_macro_job", run_macro_job)
    ctx = mpd.DispatchCtx(bridge=env.bridge, pool=env.bridge._page_pool, urls=[owner])
    await mpd.run_claimed_image(ctx, image(), page)
    assert called == [FF_ID], "no CDP path may run for a firefox page"
    assert finished_messages(env) == ["Ui.Vision macro ok"]
    assert not any("No controller" in m for m in log_lines(env)), "the feign no-controller gate never fires"
    page = env.bridge._page_pool.get_page(FF_ID)
    assert page.jobs_completed == 1
    assert not any("New-chat reset failed" in m for m in log_lines(env)), \
        "no CDP transport → no phantom reset warning (D-8)"


@pytest.mark.asyncio
async def test_a_failed_macro_reports_the_macro_error_not_a_save_path(tmp_path, monkeypatch):
    env = env_with(tmp_path, ff_pool())
    page = env.bridge._page_pool.get_page(FF_ID)
    owner = UrlRow.create("https://arena.ai/c/9", tab_id=FF_ID)

    async def fail(bridge, pool, tab_id):
        return True, "blocked: no profile window"
    monkeypatch.setattr(mpd.firefox_job, "run_macro_job", fail)
    ctx = mpd.DispatchCtx(bridge=env.bridge, pool=env.bridge._page_pool, urls=[owner])
    await mpd.run_claimed_image(ctx, image(), page)
    assert finished_messages(env) == ["blocked: no profile window"]


def test_the_no_controller_gate_still_covers_chrome_pages():
    chrome = SimpleNamespace(browser="chrome", tab_id="t1")
    assert mpd.is_firefox(getattr(chrome, "browser", "")) is False
    ff = SimpleNamespace(browser="firefox", tab_id=FF_ID)
    assert mpd.is_firefox(getattr(ff, "browser", "")) is True
    legacy = SimpleNamespace(tab_id="t1")           # a page with no browser id = chrome
    assert mpd.is_firefox(getattr(legacy, "browser", "")) is False


@pytest.mark.asyncio
async def test_the_finish_ctx_of_a_firefox_job_carries_no_transport(tmp_path):
    env = env_with(tmp_path, ff_pool())
    job = mpd.PageJobCtx(bridge=env.bridge, pool=env.bridge._page_pool, img=image(),
                         urls=[], tab_id=FF_ID, ctrl=object(), client=object(),
                         browser="firefox")
    finish = mpd._finish_ctx(job)
    assert finish.ctrl is None and finish.client is None
    chrome_job = mpd.PageJobCtx(bridge=env.bridge, pool=env.bridge._page_pool, img=image(),
                                urls=[], tab_id="t1", ctrl="c", client="x", browser="chrome")
    chrome_finish = mpd._finish_ctx(chrome_job)
    assert chrome_finish.ctrl == "c" and chrome_finish.client == "x"
    assert mpd._done_msg(job) == "Ui.Vision macro ok"
    assert mpd._done_msg(chrome_job) == ""


# ── the sequential lane ──────────────────────────────────────────────────────

def batch_env(tmp_path):
    env = env_with(tmp_path, ff_pool())
    ctx = BatchCtx(bridge=env.bridge, ctrl=None, tab_id=FF_ID, prompt_template="{p}")
    return env, ctx


@pytest.mark.asyncio
async def test_the_sequential_lane_executes_the_macro_with_ids_and_honest_text(tmp_path, monkeypatch):
    env, ctx = batch_env(tmp_path)
    called = []

    async def run_macro_job(bridge, pool, tab_id):
        called.append((tab_id, pool))
        return False, ""
    monkeypatch.setattr("app.services.batch_orchestrator.firefox_job.run_macro_job", run_macro_job)
    res = await _execute_firefox(ctx, image(), UrlRow.create("https://arena.ai/c/9"))
    assert called and called[0][0] == FF_ID
    assert res.done_msg == "Ui.Vision macro ok" and not res.failed
    assert res.job_id and res.corr_id


def test_job_finished_uses_the_override_when_present(tmp_path):
    env = env_with(tmp_path, ff_pool())
    res = ImageResult(img=image(), failed=False, error="", job_id="j1",
                      corr_id="c1", done_msg="Ui.Vision macro ok")
    _emit_job_finished(env.bridge, res)
    assert finished_messages(env) == ["Ui.Vision macro ok"]
    plain = ImageResult(img=image(), failed=False, error="", job_id="j2", corr_id="c2")
    _emit_job_finished(env.bridge, plain)
    assert finished_messages(env)[-1].startswith("Saved to ")


@pytest.mark.asyncio
async def test_the_sequential_finish_skips_the_cdp_reset_for_firefox(tmp_path):
    env, ctx = batch_env(tmp_path)
    await _finish_primary_tab(ctx)
    assert env.bridge._page_pool.get_page(FF_ID).jobs_completed == 1
    assert not any("New-chat reset failed" in m for m in log_lines(env))


@pytest.mark.asyncio
async def test_a_move_to_a_firefox_tab_never_touches_cdp(tmp_path):
    env, _ctx = batch_env(tmp_path)
    bomb = SimpleNamespace(connect=lambda _ws: (_ for _ in ()).throw(AssertionError("cdp touched")))
    env.bridge.cdp = bomb
    moved = await _move_to_tab(env.bridge, "t1", FF_ID)
    assert moved == FF_ID
    assert any("firefox — no socket" in m for m in log_lines(env))


# ── the supervisor's ladder ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_free_firefox_worker_makes_cdp_down_a_runnable_pass(tmp_path, monkeypatch):
    from app.services.live import supervisor as sv_live
    env = env_with(tmp_path, ff_pool())
    env.bridge.state.urls = [UrlRow.create("https://arena.ai/c/9", tab_id=FF_ID)]
    env.bridge.cdp.is_connected = False

    async def claim(bridge, current, allowed):
        return FF_ID if FF_ID in allowed else ""
    monkeypatch.setattr(sv_live, "resolve_and_claim_tab", claim)
    plan = await sv_live.plan_pass(env.bridge)
    assert plan.reason == "" and plan.tab_id == FF_ID
    assert FF_ID in plan.allowed


@pytest.mark.asyncio
async def test_without_a_ready_firefox_worker_cdp_down_remains_a_wait(tmp_path):
    from app.services.live import supervisor as sv_live
    env = env_with(tmp_path, ff_pool())
    env.bridge.state.urls = [UrlRow.create("https://arena.ai/c/9", tab_id=FF_ID, enabled=False)]
    env.bridge.cdp.is_connected = False
    plan = await sv_live.plan_pass(env.bridge)
    assert plan.reason == "cdp down", "an unchecked row's tab is not a worker"


def test_firefox_ready_needs_free_allowed_firefox_pages(tmp_path):
    from app.browser.page_status import PageStatus
    from app.services.live.supervisor import _firefox_ready
    pool = ff_pool()
    page = pool.get_page(FF_ID)
    assert _firefox_ready(SimpleNamespace(_page_pool=pool), {FF_ID}) is True
    assert _firefox_ready(SimpleNamespace(_page_pool=pool), {"other"}) is False
    page.status = PageStatus.COOLDOWN           # cooling ≠ ready
    assert _firefox_ready(SimpleNamespace(_page_pool=pool), {FF_ID}) is False
    assert _firefox_ready(SimpleNamespace(), {FF_ID}) is False      # no pool → not ready


# ── the cooldown finish ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_transportless_finish_counts_success_without_touching_the_reset(tmp_path, monkeypatch):
    env = env_with(tmp_path, ff_pool())
    called = []

    async def boom(_ctx):
        called.append(1)
        raise AssertionError("reset must not run without a transport")
    monkeypatch.setattr(cds, "reset_to_new_chat", boom)
    ctx = cds.FinishCtx(pool=env.bridge._page_pool, bridge=env.bridge, tab_id=FF_ID,
                        ctrl=None, client=None)
    ok, reason = await cds._best_effort_reset(ctx, 30.0)
    assert (ok, reason) == (True, "") and called == []
