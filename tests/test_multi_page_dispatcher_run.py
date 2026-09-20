"""D4.1: multi_page_dispatcher run lifecycle — acquire, run, finish, settle, batch.

RULE 8: real PagePool/dispatcher; the job runner seam (capture_baseline /
run_blocks_for_image) and the post-job finish are faked at the unit boundary —
the runner itself is exercised end-to-end by tests/characterization goldens.
"""

import asyncio

import pytest

from app.browser.page_pool import PagePool
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
    def __init__(self, cancel=False, pause=False, stop_after=False):
        from types import SimpleNamespace
        self.state = SimpleNamespace(prompt={"user_prompt": "go"},
                                     recalculate_progress=lambda: None)
        self.job_started = Emitter()
        self.job_finished = Emitter()
        self._cancel_requested = cancel
        self._pause_requested = pause
        self._stop_after = stop_after
        self._run_state = "running"
        self.logs = []
        self.saves = 0
        self.pool_emits = 0
        self.arena_emits = 0
        from types import SimpleNamespace as NS
        self.config = NS(get_state=lambda: {})

    def _save_arena(self):
        self.saves += 1

    def _emit_pool_status(self):
        self.pool_emits += 1

    def _emit_arena_state(self):
        self.arena_emits += 1

    def _log(self, message, level="info"):
        self.logs.append((level, message))


def make_img(name="a.png", **kw):
    data = {"id": kw.get("id", "i-" + name), "relative_path": name,
            "absolute_path": f"/tmp/{name}", "filename": name,
            "base_name": name.rsplit(".", 1)[0], "extension": "." + name.rsplit(".", 1)[1],
            "size": 1, "mtime": 0.0, "fingerprint": "fp-" + name}
    return ImageItem.from_scan_dict(data)


def make_pool(tab_ids, busy=()):
    # add_page force-resets status to STEADY (pool design) — busy comes after
    pool = PagePool()
    for tab in tab_ids:
        pool.add_page(PageInfo(ws_url=f"ws://{tab}", tab_id=tab, title=f"T-{tab}",
                               url="https://arena.ai", is_connected=True, jobs_completed=0))
    for tab in busy:
        pool.mark_busy(tab, "other-job")
    return pool


def make_urls(tab_ids, enabled=True):
    return [UrlRow.create(f"https://arena.ai/{t}", enabled=enabled, tab_id=t) for t in tab_ids]


@pytest.fixture
def runner_fakes(monkeypatch):
    """Fake the job-runner seam; return a record list mutated by the fakes."""
    record = {"failed": False, "error": "", "raise": None, "on_run": None, "calls": 0}

    async def fake_baseline(ctrl):
        return {"outputs": []}

    async def fake_run(job_ctx):
        record["calls"] += 1
        if record["raise"] is not None:
            raise record["raise"]
        if callable(record.get("on_run")):
            record["on_run"](job_ctx)
        return record["failed"], record["error"], None, None

    monkeypatch.setattr(mpd, "capture_baseline", fake_baseline)
    monkeypatch.setattr(mpd, "run_blocks_for_image", fake_run)

    async def fake_finish(ctx):
        ctx.pool.mark_steady(ctx.tab_id)

    monkeypatch.setattr(mpd, "finish_page_after_job", fake_finish)
    # bound the production 600s free-page wait for the no-free-path test
    monkeypatch.setattr(mpd, "cooldown_aware_timeout", lambda pool: 0.1)
    return record


@pytest.mark.asyncio
async def test_run_success_completes_image_and_finishes_page(runner_fakes):
    pool = make_pool(["t1"])
    pool.register_client("t1", object(), object())
    bridge = FakeBridge()
    img = make_img()
    await mpd.run_one_image_on_page(bridge, pool, img, make_urls(["t1"]))
    assert img.status == ImageStatus.COMPLETED.value
    assert bridge.job_started.calls and bridge.job_finished.calls
    assert "completed" in bridge.job_finished.calls[0][1]
    assert pool.get_page("t1").status == PageStatus.STEADY
    assert any("📤" in msg for _, msg in bridge.logs if isinstance(msg, str))


@pytest.mark.asyncio
async def test_run_failure_marks_failed_and_emits_error(runner_fakes):
    runner_fakes.update(failed=True, error="block exploded")
    pool = make_pool(["t1"])
    pool.register_client("t1", object(), object())
    bridge = FakeBridge()
    img = make_img()
    await mpd.run_one_image_on_page(bridge, pool, img, make_urls(["t1"]))
    assert img.status == ImageStatus.FAILED.value and img.error == "block exploded"
    assert "failed" in bridge.job_finished.calls[0][1]
    assert any(level == "error" for level, _ in bridge.logs)


@pytest.mark.asyncio
async def test_run_cancel_before_start_is_noop(runner_fakes):
    pool = make_pool(["t1"])
    pool.register_client("t1", object(), object())
    bridge = FakeBridge(cancel=True)
    img = make_img()
    await mpd.run_one_image_on_page(bridge, pool, img, make_urls(["t1"]))
    assert img.status != ImageStatus.PROCESSING.value
    assert runner_fakes["calls"] == 0 and not bridge.job_finished.calls


@pytest.mark.asyncio
async def test_settled_image_never_acquires_a_page(runner_fakes):
    """B13 / I-44: the worker re-checks the status right before the claim."""
    pool = make_pool(["t1"])
    pool.register_client("t1", object(), object())
    bridge = FakeBridge()
    done = make_img("done.png")
    done.status, done.attempt_count, done.selected = ImageStatus.COMPLETED.value, 1, True
    fresh = make_img("fresh.png")
    ctx = mpd.DispatchCtx(bridge=bridge, pool=pool, urls=make_urls(["t1"]),
                          sem=asyncio.Semaphore(1), allowed={"t1"})
    await mpd._run_with_sem(ctx, done)
    await mpd._run_with_sem(ctx, fresh)
    assert (done.status, done.attempt_count) == (ImageStatus.COMPLETED.value, 1)
    assert fresh.status == ImageStatus.COMPLETED.value and fresh.attempt_count == 1
    assert runner_fakes["calls"] == 1
    assert [p for _, p in bridge.job_started.calls] == ["/tmp/fresh.png"]
    assert ("info", "⏭ Skipping done.png — already completed") in bridge.logs
    assert pool.get_page("t1").status == PageStatus.STEADY


@pytest.mark.asyncio
async def test_run_no_free_page_logs_warning(runner_fakes):
    pool = make_pool(["t1"], busy=("t1",))
    bridge = FakeBridge()
    img = make_img()
    await mpd.run_one_image_on_page(bridge, pool, img, make_urls(["t1"]))
    assert runner_fakes["calls"] == 0
    assert any("No free page" in msg for _, msg in bridge.logs if isinstance(msg, str))
    assert img.status != ImageStatus.PROCESSING.value


@pytest.mark.asyncio
async def test_run_without_registered_controller_marks_steady(runner_fakes):
    pool = make_pool(["t1"])  # no register_client
    bridge = FakeBridge()
    img = make_img()
    await mpd.run_one_image_on_page(bridge, pool, img, make_urls(["t1"]))
    assert runner_fakes["calls"] == 0
    assert any("No controller" in msg for _, msg in bridge.logs if isinstance(msg, str))
    assert pool.get_page("t1").status == PageStatus.STEADY


@pytest.mark.asyncio
async def test_run_job_exception_fails_image_with_reason(runner_fakes):
    runner_fakes["raise"] = RuntimeError("cdp dropped")
    pool = make_pool(["t1"])
    pool.register_client("t1", object(), object())
    bridge = FakeBridge()
    img = make_img()
    await mpd.run_one_image_on_page(bridge, pool, img, make_urls(["t1"]))
    assert img.status == ImageStatus.FAILED.value and "cdp dropped" in img.error
    assert any("failed: cdp dropped" in msg for _, msg in bridge.logs if isinstance(msg, str))


@pytest.mark.asyncio
async def test_run_cancelled_mid_job_marks_cancelled(runner_fakes):
    def on_run(job_ctx):
        job_ctx.bridge._cancel_requested = True

    runner_fakes["on_run"] = on_run
    pool = make_pool(["t1"])
    pool.register_client("t1", object(), object())
    bridge = FakeBridge()
    img = make_img()
    await mpd.run_one_image_on_page(bridge, pool, img, make_urls(["t1"]))
    assert img.status == ImageStatus.FAILED.value and img.error == "Cancelled"
    assert not bridge.job_finished.calls  # cancelled job emits no finished payload


@pytest.mark.asyncio
async def test_finish_page_safely_settles_on_error_and_reraises_cancel(monkeypatch):
    pool = make_pool(["t1"])
    page = pool.get_page("t1")
    page.status = PageStatus.ERROR  # stuck
    bridge = FakeBridge()
    from app.services.cooldown_service import FinishCtx

    async def boom(ctx):
        raise RuntimeError("reset failed")

    async def cancelled(ctx):
        raise asyncio.CancelledError()

    monkeypatch.setattr(mpd, "finish_page_after_job", boom)
    await mpd._finish_page_safely(FinishCtx(pool=pool, bridge=bridge, tab_id="t1",
                                            ctrl=None, client=None))
    assert pool.get_page("t1").status == PageStatus.STEADY  # stuck settled

    monkeypatch.setattr(mpd, "finish_page_after_job", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await mpd._finish_page_safely(FinishCtx(pool=pool, bridge=bridge, tab_id="t1",
                                                ctrl=None, client=None))


@pytest.mark.asyncio
async def test_dispatch_parallel_runs_all_images(runner_fakes):
    pool = make_pool(["t1", "t2"])
    pool.register_client("t1", object(), object())
    pool.register_client("t2", object(), object())
    bridge = FakeBridge()
    imgs = [make_img("a.png", id="i1"), make_img("b.png", id="i2")]
    await mpd.dispatch_parallel(bridge, pool, imgs, make_urls(["t1", "t2"]))
    assert all(img.status == ImageStatus.COMPLETED.value for img in imgs)
    assert bridge._run_state == "idle"
    assert bridge.arena_emits >= 1
    assert any("Parallel batch complete" in msg for _, msg in bridge.logs if isinstance(msg, str))


@pytest.mark.asyncio
async def test_dispatch_parallel_skips_without_checked_tabs(runner_fakes):
    pool = make_pool(["t1"])
    bridge = FakeBridge()
    img = make_img()
    await mpd.dispatch_parallel(bridge, pool, [img], make_urls(["t1"], enabled=False))
    assert runner_fakes["calls"] == 0 and img.status != ImageStatus.PROCESSING.value
    assert any("no checked URL owns a tab" in msg for _, msg in bridge.logs if isinstance(msg, str))
    await mpd.dispatch_parallel(bridge, None, [img], make_urls(["t1"]))  # no pool: no-op
    assert runner_fakes["calls"] == 0


@pytest.mark.asyncio
async def test_dispatch_parallel_stops_when_cancel_flips(runner_fakes):
    def on_run(job_ctx):
        job_ctx.bridge._cancel_requested = True

    runner_fakes["on_run"] = on_run
    pool = make_pool(["t1", "t2"])
    pool.register_client("t1", object(), object())
    pool.register_client("t2", object(), object())
    bridge = FakeBridge()
    imgs = [make_img("a.png", id="i1"), make_img("b.png", id="i2")]
    await mpd.dispatch_parallel(bridge, pool, imgs, make_urls(["t1", "t2"]))
    assert runner_fakes["calls"] == 1  # second task never created
    assert imgs[1].status != ImageStatus.PROCESSING.value


@pytest.mark.asyncio
async def test_dispatch_parallel_honours_stop_after(runner_fakes):
    pool = make_pool(["t1"])
    pool.register_client("t1", object(), object())
    bridge = FakeBridge(stop_after=True)
    img = make_img()
    await mpd.dispatch_parallel(bridge, pool, [img], make_urls(["t1"]))
    assert runner_fakes["calls"] == 0 and img.status != ImageStatus.PROCESSING.value
    assert bridge._run_state == "idle"  # finalization still runs


@pytest.mark.asyncio
async def test_wait_pause_releases_when_pause_cleared(monkeypatch):
    bridge = FakeBridge(pause=True)
    sleeps = []

    async def instant_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            bridge._pause_requested = False

    monkeypatch.setattr(mpd.asyncio, "sleep", instant_sleep)
    await mpd._wait_pause(bridge)
    assert bridge._pause_requested is False
    assert sleeps  # the loop actually polled


@pytest.mark.asyncio
async def test_wait_pause_breaks_on_cancel(monkeypatch):
    bridge = FakeBridge(pause=True, cancel=True)
    sleeps = []

    async def instant_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(mpd.asyncio, "sleep", instant_sleep)
    await mpd._wait_pause(bridge)
    assert len(sleeps) == 1  # one poll, then cancel breaks
