"""Firefox through the ONE dispatcher (2026-09-25, design D5/D6).

`run_claimed_image` routes a `browser == "firefox"` page to the image-job
lane with the SAME bookkeeping as the Chrome lane (prepare → job_started →
result → shared finish). A saved file is counted and says `Saved …`. A miss
is not counted (I-65). The phase behavior itself lives in
`tests/test_firefox_image_job.py`.

RED at base: a Firefox page hits "⚠ No controller" and the job never runs.
"""

import asyncio
from types import SimpleNamespace as NS

import pytest

from app.browser.page_status import PageInfo, PageStatus
from app.core.enums import ImageStatus
from app.core.models import ImageItem, UrlRow
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


async def _noop_finish(finish_ctx):
    return None


@pytest.mark.asyncio
async def test_saved_file_is_counted_and_says_saved(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    persisted = []
    bridge._persist_cooldowns = lambda: persisted.append(1)

    async def saved(job, page, options=None):
        job.img.output_path = "/tmp/a_AI.png"
        job.img.status = ImageStatus.COMPLETED.value

    monkeypatch.setattr("app.services.firefox_image.runner.run_firefox_image", saved)
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.COMPLETED.value
    assert bridge.job_started.calls and bridge.job_finished.calls
    payload = bridge.job_finished.calls[-1][1]
    assert "Saved /tmp/a_AI.png" in payload
    page = pool.get_page(row.tab_id)
    assert page.jobs_completed == 1
    assert persisted == [1]
    assert page.status == PageStatus.COOLDOWN


@pytest.mark.asyncio
async def test_a_miss_is_not_counted(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    persisted = []
    bridge._persist_cooldowns = lambda: persisted.append(1)

    async def missed(job, page, options=None):
        job.img.status = ImageStatus.FAILED.value
        job.img.error = "E210 no matching tab"

    monkeypatch.setattr("app.services.firefox_image.runner.run_firefox_image", missed)
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.FAILED.value
    assert "E210 no matching tab" in img.error
    payload = bridge.job_finished.calls[-1][1]
    assert "E210 no matching tab" in payload
    assert pool.get_page(row.tab_id).jobs_completed == 0
    assert persisted == []


@pytest.mark.asyncio
async def test_cancel_before_submit_emits_no_finished_event(monkeypatch):
    """I-61: a clean cancel leaves no job_finished and no history row."""
    bridge, pool = FakeBridge(), firefox_pool()
    bridge._cancel_requested = True
    recorded = []
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: recorded.append(ctx))

    async def cancelled(job, page, options=None):
        job.img.status = ImageStatus.FAILED.value
        job.img.error = "Cancelled"

    monkeypatch.setattr("app.services.firefox_image.runner.run_firefox_image", cancelled)
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.error == "Cancelled"
    assert bridge.job_finished.calls == []
    assert recorded == []
    assert pool.get_page(row.tab_id).jobs_completed == 0


@pytest.mark.asyncio
async def test_needs_review_is_not_counted_and_not_completed(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)

    async def review(job, page, options=None):
        job.img.status = ImageStatus.NEEDS_REVIEW.value
        job.img.error = "multiple result candidates"

    monkeypatch.setattr("app.services.firefox_image.runner.run_firefox_image", review)
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.NEEDS_REVIEW.value
    payload = bridge.job_finished.calls[-1][1]
    assert "needs_review" in payload
    assert "multiple result candidates" in payload
    assert pool.get_page(row.tab_id).jobs_completed == 0


@pytest.mark.asyncio
async def test_finish_after_a_firefox_job_never_fakes_a_cdp_reset(monkeypatch, tmp_path):
    """ctrl=None: the shared finish must say "no CDP" instead of a reset failure."""
    from app.services.cooldown_service import FinishCtx, _best_effort_reset
    bridge, pool = FakeBridge(), firefox_pool()
    ctx = FinishCtx(pool=pool, bridge=bridge, tab_id="9THrgpBc.Profile1_tab1",
                    ctrl=None, client=None)
    ok, reason = await _best_effort_reset(ctx, timeout_sec=0.1)
    assert ok is False
    assert "firefox" in reason.lower() or "no cdp" in reason.lower()
    assert "Traceback" not in reason


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
async def test_verdict_names_a_tab_that_left_the_pool():
    """Page vanished between claim and macro: an honest failure, never a crash."""
    from app.browser.page_pool import PagePool
    job = NS(pool=PagePool(logger=lambda m, l="info": None), bridge=FakeBridge(),
             tab_id="9THrgpBc.Profile1_tab1")
    failed, err = await mpd._firefox_verdict(job)
    assert failed is True
    assert "tab left the pool" in err


@pytest.mark.asyncio
async def test_verdict_crash_becomes_a_named_failure(monkeypatch):
    async def boom(job, page, options=None):
        raise RuntimeError("desktop gone")

    monkeypatch.setattr("app.services.firefox_image.runner.run_firefox_image", boom)
    job = NS(pool=firefox_pool(), bridge=FakeBridge(),
             tab_id="9THrgpBc.Profile1_tab1")
    failed, err = await mpd._firefox_verdict(job)
    assert failed is True
    assert err == "Ui.Vision blocked: desktop gone"


@pytest.mark.asyncio
async def test_verdict_cancel_propagates_to_the_dispatcher(monkeypatch):
    async def cancelled(job, page, options=None):
        raise asyncio.CancelledError()

    monkeypatch.setattr("app.services.firefox_image.runner.run_firefox_image", cancelled)
    job = NS(pool=firefox_pool(), bridge=FakeBridge(),
             tab_id="9THrgpBc.Profile1_tab1")
    with pytest.raises(asyncio.CancelledError):
        await mpd._firefox_verdict(job)


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

    async def ok_job(job, page, options=None):
        job.img.output_path = "/tmp/a_AI.png"
        job.img.status = ImageStatus.COMPLETED.value

    monkeypatch.setattr("app.services.firefox_image.runner.run_firefox_image", ok_job)
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.COMPLETED.value
