"""Firefox through the ONE dispatcher (design D5/D6 + image job D-1, 2026-09-25).

`run_claimed_image` routes a `browser == "firefox"` page to `firefox_job`
with the SAME bookkeeping as the Chrome lane (prepare → job_started → result
→ shared finish/cooldown/bus wake). The verdict decides the image honestly:
completed = "Saved <file>", failed = the named reason, needs_review = its
own status; the job's Ui.Vision New Chat reaches the shared finish through
the `FinishCtx.lane_reset` seam (Chrome passes None — unchanged).
"""

import asyncio
from types import SimpleNamespace as NS

import pytest

from app.browser.page_status import PageInfo, PageStatus
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


def fake_job(monkeypatch, verdict, saved="", resets=None, raises=None):
    """`run_job` stand-in: hands the finish seam a reset first, like the real one."""
    seen = {}

    async def run_job(start, reset_out):
        seen["start"] = start

        async def reset():
            (resets if resets is not None else []).append(start.corr)
            return True, "New Chat — clean page verified"
        reset_out.append(reset)
        if raises:
            raise raises
        if saved:
            start.img.output_path = saved
        return verdict

    monkeypatch.setattr(fj, "run_job", run_job)
    return seen


@pytest.mark.asyncio
async def test_saved_job_completes_counts_and_resets_through_the_seam(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    resets = []
    seen = fake_job(monkeypatch, fj.Verdict(False), saved="/tmp/a_AI.png", resets=resets)
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.COMPLETED.value
    assert "[JOB-ID:" in seen["start"].prompt and seen["start"].tab_id == row.tab_id
    assert bridge.job_started.calls and "Saved /tmp/a_AI.png" in bridge.job_finished.calls[-1][1]
    assert pool.get_page(row.tab_id).jobs_completed == 1   # shared finish: JOBS column moves
    assert resets == [seen["start"].corr]                  # New Chat via Ui.Vision, not CDP


@pytest.mark.asyncio
async def test_failed_job_fails_the_image_with_the_reason_and_still_counts(monkeypatch):
    """Owner: the count follows Chrome — every finished non-cancelled job counts."""
    bridge, pool = FakeBridge(), firefox_pool()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    fake_job(monkeypatch, fj.Verdict(True, "attachment not visible after the upload"))
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.FAILED.value
    assert img.error == "attachment not visible after the upload"
    assert "attachment not visible" in bridge.job_finished.calls[-1][1]
    assert pool.get_page(row.tab_id).jobs_completed == 1


@pytest.mark.asyncio
async def test_review_verdict_lands_as_needs_review_with_a_history_row(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    rows = []
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: rows.append(ctx.err))
    fake_job(monkeypatch, fj.Verdict(True, "needs review — generation timed out", True))
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.NEEDS_REVIEW.value
    assert "needs review" in img.error and rows == ["needs review — generation timed out"]


@pytest.mark.asyncio
async def test_cancel_propagates_and_the_finish_still_runs_with_the_seam(monkeypatch):
    bridge, pool = FakeBridge(), firefox_pool()
    finishes = []

    async def spy_finish(finish_ctx):
        finishes.append(finish_ctx.lane_reset)

    monkeypatch.setattr(mpd, "_finish_page_safely", spy_finish)
    fake_job(monkeypatch, None, raises=asyncio.CancelledError())
    ctx, row = ctx_for(bridge, pool, make_img())
    with pytest.raises(asyncio.CancelledError):
        await mpd._run_firefox_claimed(ctx, make_img(), pool.get_page(row.tab_id))
    assert len(finishes) == 1 and callable(finishes[0])


@pytest.mark.asyncio
async def test_finish_after_a_firefox_job_never_fakes_a_cdp_reset(monkeypatch, tmp_path):
    """ctrl=None and no lane seam: the shared finish says "no CDP" instead of a reset failure."""
    from app.services.cooldown_service import FinishCtx, _best_effort_reset
    bridge, pool = FakeBridge(), firefox_pool()
    ctx = FinishCtx(pool=pool, bridge=bridge, tab_id="9THrgpBc.Profile1_tab1",
                    ctrl=None, client=None)
    ok, reason = await _best_effort_reset(ctx, timeout_sec=0.1)
    assert ok is False
    assert "firefox" in reason.lower() or "no cdp" in reason.lower()
    assert "Traceback" not in reason


@pytest.mark.asyncio
async def test_lane_reset_seam_answers_and_never_raises():
    from app.services.cooldown_service import FinishCtx, _best_effort_reset

    async def good():
        return True, "clean"

    async def bad():
        raise RuntimeError("macro gone")

    ctx = FinishCtx(pool=None, bridge=FakeBridge(), tab_id="t", ctrl=None, client=None, lane_reset=good)
    assert await _best_effort_reset(ctx, timeout_sec=1) == (True, "clean")
    ctx.lane_reset = bad
    assert await _best_effort_reset(ctx, timeout_sec=1) == (False, "macro gone")


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
async def test_job_started_emit_failure_never_kills_the_lane(monkeypatch):
    """A dead Qt signal must not abort the job — the try/except exists, drive it."""
    bridge, pool = FakeBridge(), firefox_pool()

    class DeadEmitter:
        def emit(self, *args):
            raise RuntimeError("signal channel closed")

    bridge.job_started = DeadEmitter()
    monkeypatch.setattr(mpd, "record_dispatch_result", lambda ctx: None)
    monkeypatch.setattr(mpd, "_finish_page_safely", _noop_finish)
    fake_job(monkeypatch, fj.Verdict(False), saved="/tmp/a_AI.png")
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_a_save_that_beat_the_cancel_stays_completed(monkeypatch):
    """The file IS beside the source — `_handle_result`'s "Cancelled" must not hide it (RULE 4)."""
    bridge, pool = FakeBridge(), firefox_pool()
    rows = []
    monkeypatch.setattr(fj, "record_dispatch_result", lambda ctx: rows.append(ctx.failed))
    monkeypatch.setattr(mpd, "_finish_page_safely", _noop_finish)

    async def run_job(start, reset_out):
        bridge._cancel_requested = True       # Cancel clicked while the save ran
        start.img.output_path = "/tmp/a_AI.png"
        return fj.Verdict(False)

    monkeypatch.setattr(fj, "run_job", run_job)
    ctx, row = ctx_for(bridge, pool, make_img())
    img = make_img()
    await mpd._run_firefox_claimed(ctx, img, pool.get_page(row.tab_id))
    assert img.status == ImageStatus.COMPLETED.value and img.error is None
    assert rows == [False]                    # its Job History row is written after all
