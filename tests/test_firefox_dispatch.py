"""Firefox through the ONE dispatcher (2026-09-25, steps 14–19).

`run_claimed_image` routes a `browser == "firefox"` page to the Firefox image
job (`services/firefox_job.run_image_job`) with the SAME bookkeeping as the
Chrome lane (prepare → job_started → result → shared finish/cooldown/bus wake);
the image outcome follows the job's own verdict HONESTLY — `completed` carries
the real saved path, `needs_review` marks the image for a human and is never
rounded to completed, a failure keeps the named reason, cancel propagates.

The framework test (`firefox_lane.run_firefox_macro`, the window's own Run
button) is NOT what a dispatched job runs any more — that is the whole point of
this round.
"""

import asyncio
from types import SimpleNamespace as NS

import pytest

from app.browser.page_status import PageInfo
from app.core.enums import ImageStatus
from app.core.models import ImageItem, UrlRow
from app.services import firefox_job as fj
from app.services import multi_page_dispatcher as mpd

pytestmark = pytest.mark.unit


class Emitter:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class FakeBridge:
    def __init__(self):
        self.state = NS(prompt={"user_prompt": "go"}, images=[],
                        recalculate_progress=lambda: None)
        self.job_started = Emitter()
        self.job_finished = Emitter()
        self._cancel_requested = False
        self._pause_requested = False
        self._stop_after = False
        self._run_state = "running"
        self.logs = []
        self.config = NS(get_state=lambda key, default=None: default, dir="/tmp/cfg")

    def _save_arena(self):
        pass

    def _emit_pool_status(self):
        self.logs.append(("info", "pool-emit"))

    def _emit_arena_state(self):
        pass

    def _log(self, message, level="info"):
        self.logs.append((level, message))


def make_img(name="a.png"):
    data = {"id": "i-" + name, "relative_path": name, "absolute_path": f"/tmp/{name}",
            "filename": name, "base_name": name.rsplit(".", 1)[0],
            "extension": name.rsplit(".", 1)[1], "size": 1, "mtime": 0.0,
            "fingerprint": "fp-" + name}
    item = ImageItem.from_scan_dict(data)
    item.selected = True
    return item


def firefox_pool(tab_id="9THrgpBc.Profile1_tab1"):
    from app.browser.page_pool import PagePool
    from app.browser.uivision import pool_tabs as pt
    pool = PagePool(logger=lambda m, l="info": None)
    tab = pt.FirefoxTab(id=tab_id, url="https://arena.ai/c/7", title="A",
                        profile="P1", profile_dir="/x/P1", ws_url=f"firefox://{tab_id}")
    pool.add_page(pt.page_for(tab))
    return pool


def ctx_for(bridge, pool, img, urls=None):
    row = UrlRow.create("https://arena.ai/c/7", enabled=True,
                        tab_id="9THrgpBc.Profile1_tab1")
    return mpd.DispatchCtx(bridge=bridge, pool=pool, urls=list(urls or [row]),
                           allowed={row.tab_id}), row


async def _noop_finish(finish_ctx):
    return None


def _outcome(monkeypatch, outcome):
    """Patch the job seam the dispatcher calls (the real job is tested elsewhere)."""
    async def fake_job(request):
        return outcome
    monkeypatch.setattr(fj, "run_image_job", fake_job)


@pytest.mark.asyncio
async def test_run_claimed_image_routes_firefox_to_the_lane(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    called = []

    async def spy_lane(ctx, img, page):
        called.append((img.id, page.tab_id))

    monkeypatch.setattr(mpd, "_run_firefox_claimed", spy_lane)
    monkeypatch.setattr(mpd, "_finish_page_safely", _noop_finish)
    ctx, _row = ctx_for(bridge, pool, make_img())
    page = pool.get_page("9THrgpBc.Profile1_tab1")
    await mpd.run_claimed_image(ctx, make_img(), page)
    assert called, "the firefox branch must own the job (no CDP controller path)"


@pytest.mark.asyncio
async def test_completed_job_marks_the_image_and_the_jobs_column(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    _outcome(monkeypatch, fj.JobOutcome(fj.COMPLETED, output_path="/tmp/a_AI.png"))
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.COMPLETED.value
    assert bridge.job_started.calls and bridge.job_finished.calls
    payload = bridge.job_finished.calls[-1][1]
    assert "Saved /tmp/a_AI.png" in payload          # the real file, never invented
    assert pool.get_page(row.tab_id).jobs_completed >= 1   # shared finish: JOBS column moves


@pytest.mark.asyncio
async def test_failed_job_keeps_the_named_reason(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    _outcome(monkeypatch, fj.JobOutcome(fj.FAILED, error="attachment not verified: no attachment preview"))
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.FAILED.value
    assert "no attachment preview" in img.error
    page = pool.get_page(row.tab_id)
    assert page.jobs_completed == 0            # nothing was saved → the JOBS column stays
    assert page.status.value == "error" and not page.is_cooling()   # a human resets it


@pytest.mark.asyncio
async def test_needs_review_never_becomes_completed(monkeypatch):
    """Uncertain output: the image is marked for a human and the page keeps its evidence."""
    bridge, pool = FakeBridge(), firefox_pool()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    _outcome(monkeypatch, fj.JobOutcome(fj.NEEDS_REVIEW, error="result uncertain: no new image"))
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.NEEDS_REVIEW.value
    assert "uncertain" in img.error
    payload = bridge.job_finished.calls[-1][1]
    assert "needs_review" in payload and "completed" not in payload
    assert pool.get_page(row.tab_id).status.value == "error"   # preserved, not free
    assert "no new job" in " ".join(m for _lvl, m in bridge.logs)


@pytest.mark.asyncio
async def test_finish_after_a_firefox_job_runs_the_macro_reset(monkeypatch, tmp_path):
    """ctrl=None on a Firefox page: the reset goes through its own macro (step 15)."""
    from app.services.cooldown_service import FinishCtx, _best_effort_reset
    bridge, pool = FakeBridge(), firefox_pool()
    calls = []

    async def fake_reset(b, page):
        calls.append(page.tab_id)
        return True, "composer empty, nothing attached, no spinner, no dialog"

    monkeypatch.setattr("app.services.firefox_lane.reset_page", fake_reset)
    ctx = FinishCtx(pool=pool, bridge=bridge, tab_id="9THrgpBc.Profile1_tab1",
                    ctrl=None, client=None)
    ok, reason = await _best_effort_reset(ctx, timeout_sec=0.1)
    assert ok is True and calls == ["9THrgpBc.Profile1_tab1"]
    assert "composer empty" in reason


@pytest.mark.asyncio
async def test_finish_of_a_non_firefox_page_without_cdp_says_so(monkeypatch):
    from app.browser.page_pool import PagePool
    from app.services.cooldown_service import FinishCtx, _best_effort_reset
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(PageInfo(ws_url="ws://x", tab_id="c1", is_connected=True, browser=""))
    ctx = FinishCtx(pool=pool, bridge=FakeBridge(), tab_id="c1", ctrl=None, client=None)
    ok, reason = await _best_effort_reset(ctx, timeout_sec=0.1)
    assert ok is False and "no CDP" in reason


@pytest.mark.asyncio
async def test_a_busy_or_cooling_firefox_worker_gets_no_second_job(monkeypatch):
    """Step 14: busy during the job, then the cooldown timer — never two jobs at once."""
    import time
    from app.browser.page_status import PageStatus
    bridge, pool = FakeBridge(), firefox_pool()
    row = UrlRow.create("https://arena.ai/c/7", enabled=True, tab_id="9THrgpBc.Profile1_tab1")
    allowed = {row.tab_id}
    first = mpd._acquire_free_in(pool, allowed, "J1")
    assert first is not None and first.tab_id == row.tab_id
    assert mpd._acquire_free_in(pool, allowed, "J2") is None      # busy: no second claim
    page = pool.get_page(row.tab_id)
    page.status = PageStatus.STEADY
    page.cooldown_until = time.time() + 60                        # cooling with a live timer
    assert mpd._acquire_free_in(pool, allowed, "J3") is None      # cooldown: still no job
    page.cooldown_until = 0.0
    assert mpd._acquire_free_in(pool, allowed, "J4") is not None  # timer gone → claimable


@pytest.mark.asyncio
async def test_a_failed_new_chat_reset_is_a_warning_and_the_cooldown_still_starts(monkeypatch):
    """Step 15/18: a reset failure never turns a saved job into a failure."""
    from app.services import cooldown_service as cs
    bridge, pool = FakeBridge(), firefox_pool()
    logged = []

    async def dirty_reset(b, page):
        return False, "composer is not empty (5 chars)"

    monkeypatch.setattr("app.services.firefox_lane.reset_page", dirty_reset)
    monkeypatch.setattr(cs, "_emit_status", lambda ctx: None)
    monkeypatch.setattr(cs, "load_config", lambda get: NS(enabled=True, min_seconds=30))
    ctx = cs.FinishCtx(pool=pool, bridge=bridge, tab_id="9THrgpBc.Profile1_tab1",
                       ctrl=None, client=None)
    started = await cs.finish_page_after_job(ctx)
    text = " ".join(m for _lvl, m in bridge.logs)
    assert "New-chat reset failed" in text and "cooling anyway" in text
    assert started is True or pool.get_page(ctx.tab_id).remaining_seconds() > 0


@pytest.mark.asyncio
async def test_chrome_pages_keep_the_cdp_lane(monkeypatch):
    bridge = FakeBridge()
    pool_page = PageInfo(ws_url="ws://x", tab_id="c1", url="https://arena.ai",
                         title="T", is_connected=True, browser="chrome")
    from app.browser.page_pool import PagePool
    pool = PagePool(logger=lambda m, l="info": None)
    pool.add_page(pool_page)
    routed = []

    async def spy_lane(ctx, img, page):
        routed.append(page.tab_id)

    monkeypatch.setattr(mpd, "_run_firefox_claimed", spy_lane)
    ran = []

    async def spy_job(job):
        ran.append(job.tab_id)
        return False, "", "corr", "job"

    monkeypatch.setattr(mpd, "_run_image_job", spy_job)
    monkeypatch.setattr(mpd, "_finish_page_safely", _noop_finish)
    monkeypatch.setattr(mpd, "_get_clients", lambda pool, tab_id: (object(), object()))
    ctx, _row = ctx_for(bridge, pool, make_img(), urls=[])
    ctx.allowed = {"c1"}
    await mpd.run_claimed_image(ctx, make_img(), pool.get_page("c1"))
    assert not routed and ran == ["c1"]


@pytest.mark.asyncio
async def test_job_names_a_tab_that_left_the_pool(monkeypatch):
    """Page vanished between claim and job: an honest failure, never a crash."""
    from app.browser.page_pool import PagePool
    job = NS(pool=PagePool(logger=lambda m, l="info": None), bridge=FakeBridge(),
             tab_id="9THrgpBc.Profile1_tab1", img=make_img())
    outcome = await mpd._firefox_job(job, "corr", "job", "prompt")
    assert outcome.status == fj.FAILED
    assert "tab left the pool" in outcome.error


@pytest.mark.asyncio
async def test_job_crash_becomes_a_named_failure(monkeypatch):
    async def boom(request):
        raise RuntimeError("desktop gone")

    monkeypatch.setattr(fj, "run_image_job", boom)
    job = NS(pool=firefox_pool(), bridge=FakeBridge(), tab_id="9THrgpBc.Profile1_tab1",
             img=make_img())
    outcome = await mpd._firefox_job(job, "corr", "job", "prompt")
    assert outcome.status == fj.FAILED
    assert outcome.error == "Firefox job error: desktop gone"
    assert outcome.preserve is False


@pytest.mark.asyncio
async def test_job_cancel_propagates_to_the_dispatcher(monkeypatch):
    async def cancelled(request):
        raise asyncio.CancelledError()

    monkeypatch.setattr(fj, "run_image_job", cancelled)
    job = NS(pool=firefox_pool(), bridge=FakeBridge(), tab_id="9THrgpBc.Profile1_tab1",
             img=make_img())
    with pytest.raises(asyncio.CancelledError):
        await mpd._firefox_job(job, "corr", "job", "prompt")


@pytest.mark.asyncio
async def test_job_started_emit_failure_never_kills_the_lane(monkeypatch):
    """A dead Qt signal must not abort the job — the try/except exists, drive it."""
    bridge, pool = FakeBridge(), firefox_pool()

    class DeadEmitter:
        def emit(self, *args):
            raise RuntimeError("signal channel closed")

    bridge.job_started = DeadEmitter()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    monkeypatch.setattr(mpd, "_finish_page_safely", _noop_finish)
    _outcome(monkeypatch, fj.JobOutcome(fj.COMPLETED, output_path="/tmp/a_AI.png"))
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.COMPLETED.value
