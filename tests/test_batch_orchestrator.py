"""Batch orchestrator tests (A3): gates, claim, mark, finish, prepare, run."""

import asyncio
from types import SimpleNamespace

import pytest

from app.browser.page_pool import PagePool
from app.browser.page_status import PageInfo, PageStatus
from app.core.models import UrlRow
from app.services import batch_orchestrator as bo
from tests.characterization.harness import make_block


def make_img(name="pic1.png", status="pending", selected=True):
    return SimpleNamespace(id=name, relative_path=name, absolute_path=f"/tmp/{name}",
                           status=status, selected=selected, assigned_url_id=None,
                           attempt_count=0, output_path=None, error=None)


def make_bridge(images=None, urls=None, pool=None, tab="tab1"):
    logs = []
    finished = []
    started = []
    state = SimpleNamespace(
        images=list(images or []),
        urls=list(urls or []),
        prompt={"user_prompt": "draw x"},
        recalculate_progress=lambda: logs.append(("recalc", "")))
    return SimpleNamespace(
        state=state,
        config=SimpleNamespace(get_state=lambda k, d=None: d),
        _page_pool=pool,
        _run_state="running",
        _cancel_requested=False,
        _pause_requested=False,
        _stop_after=False,
        cdp=SimpleNamespace(_current_tab_id=tab,
                            connect=lambda ws: _connected(ws)),
        _log=lambda m, l="info": logs.append((m, l)),
        _save_arena=lambda: logs.append(("save", "")),
        _emit_arena_state=lambda: logs.append(("arena", "")),
        _emit_pool_status=lambda: logs.append(("pool", "")),
        _emit_action_blocks=lambda: logs.append(("blocks", "")),
        _get_action_blocks=lambda: [make_block("OBSERVE_BASELINE")],
        job_started=SimpleNamespace(emit=lambda j, p: started.append((j, p))),
        job_finished=SimpleNamespace(emit=lambda j, p: finished.append((j, p))),
        _logs=logs, _finished=finished, _started=started,
    )


async def _connected(ws):
    _connected.last = ws
    return True


def make_ctrl(ready=True):
    async def _ready():
        return ready, [] if ready else ["busy"]

    async def _base():
        return {"output_count": 0, "output_srcs": []}

    return SimpleNamespace(is_page_ready=_ready, capture_baseline=_base)


def make_ctx(bridge, tab_id="tab1", images=None):
    urls = bridge.state.urls
    return bo.BatchCtx(bridge=bridge, ctrl=make_ctrl(), urls=urls,
                       allowed={u.tab_id for u in urls if u.tab_id},
                       tab_id=tab_id, images=list(images or []),
                       prompt_template="draw x")


def instant_sleep(monkeypatch):
    async def _fast(_s):
        return None
    monkeypatch.setattr(asyncio, "sleep", _fast)


def pool_with(*infos):
    pool = PagePool(logger=lambda m, l="info": None)
    for info in infos:
        pool.add_page(info)
    return pool


def info(tab_id, status=PageStatus.STEADY, ws="ws://x"):
    return PageInfo(tab_id=tab_id, ws_url=ws, title=f"T-{tab_id}",
                    url="https://arena.ai", status=status, is_connected=True)


# ---- tab claim ----

@pytest.mark.asyncio
async def test_resolve_stays_and_moves():
    bridge = make_bridge()
    assert await bo.resolve_and_claim_tab(bridge, "tab1", set()) == "tab1"
    pool = pool_with(info("tab1"))
    bridge = make_bridge(pool=pool)
    assert await bo.resolve_and_claim_tab(bridge, "tab1", {"tab1"}) == "tab1"
    assert await bo.resolve_and_claim_tab(bridge, "gone", {"tab1"}) == "tab1"
    assert _connected.last == "ws://x"


@pytest.mark.asyncio
async def test_resolve_empty_and_fallbacks(monkeypatch):
    bridge = make_bridge()
    assert await bo.resolve_and_claim_tab(bridge, "", set()) == ""
    monkeypatch.setattr(bo, "resolve_primary_tab", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
    assert await bo.resolve_and_claim_tab(bridge, "tab1", set()) == "tab1"


@pytest.mark.asyncio
async def test_move_to_tab_failure_stays(monkeypatch):
    async def _no(ws):
        return False

    pool = pool_with(info("tab1"), info("tab2"))
    pool.mark_busy("tab1", "other")  # force the resolver to prefer tab2
    bridge = make_bridge(pool=pool)
    bridge.cdp.connect = _no
    assert await bo.resolve_and_claim_tab(bridge, "tab1", {"tab1", "tab2"}) == "tab1"
    assert any("staying on" in m for m, _ in bridge._logs)


def test_pool_summary_and_stay_reason():
    assert bo._pool_summary(None) == "pool n/a"
    assert bo._pool_summary(object()) == "pool n/a"
    pool = pool_with(info("tab1"))
    assert "tab1" in bo._pool_summary(pool)
    bridge = make_bridge(pool=pool)
    bo._log_stay_reason(bridge, "tab1")  # free -> silent
    assert bridge._logs == []
    pool.mark_busy("tab1", "j")
    bo._log_stay_reason(bridge, "tab1")  # busy -> warn
    assert any("No ready tab" in m for m, _ in bridge._logs)
    bo._log_stay_reason(make_bridge(), "tab1")  # no pool -> silent


# ---- gates ----

def test_should_continue_gates():
    bridge = make_bridge()
    ctx = make_ctx(bridge)
    assert bo.should_continue(ctx, make_img()) is True
    bridge._cancel_requested = True
    assert bo.should_continue(ctx, make_img()) is False
    bridge._cancel_requested = False
    bridge._stop_after = True
    assert bo.should_continue(ctx, make_img()) is False


@pytest.mark.asyncio
async def test_pause_or_abort(monkeypatch):
    instant_sleep(monkeypatch)
    ctx = make_ctx(make_bridge())
    assert await bo.await_pause_or_abort(ctx) is False
    bridge = make_bridge()
    bridge._pause_requested = True
    bridge._cancel_requested = True
    assert await bo.await_pause_or_abort(make_ctx(bridge)) is True


@pytest.mark.asyncio
async def test_claim_tab(monkeypatch):
    ctx = make_ctx(make_bridge())
    assert await bo._claim_tab(ctx) is True
    monkeypatch.setattr(bo, "resolve_and_claim_tab", lambda *a: _empty())
    assert await bo._claim_tab(ctx) is False
    assert any("No usable checked tab left" in m for m, _ in ctx.bridge._logs)


async def _empty():
    return ""


@pytest.mark.asyncio
async def test_cooldown_gate_paths():
    assert await bo.await_cooldown_if_pooled(make_ctx(make_bridge())) is True
    pool = pool_with(info("tab1"))
    ctx = make_ctx(make_bridge(pool=pool))
    assert await bo.await_cooldown_if_pooled(ctx) is True
    ctx.bridge._cancel_requested = True
    pool.get_page("tab1").status = PageStatus.COOLDOWN
    pool.get_page("tab1").cooldown_until = 9999999999.0
    assert await bo.await_cooldown_if_pooled(ctx) is False


# ---- mark + ids + finish ----

def test_mark_processing_claims_row():
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="tab1")]
    bridge = make_bridge(urls=urls)
    ctx = make_ctx(bridge)
    img = make_img()
    row = bo.mark_processing(ctx, img)
    assert row is urls[0] and img.assigned_url_id == urls[0].id
    assert img.attempt_count == 1 and img.status == "processing"
    assert ("save", "") in bridge._logs


def test_build_job_ids_announces():
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="tab1")]
    bridge = make_bridge(urls=urls)
    ctx = make_ctx(bridge)
    corr, job, final = bo.build_job_ids(ctx, make_img(), urls[0])
    assert corr == job and final.startswith(f"[JOB-ID: {corr}]")
    assert bridge._started and bridge._started[0][0] == corr
    assert any("Starting pic1.png" in m for m, _ in bridge._logs)


def test_finish_image_outcomes():
    bridge = make_bridge()
    ctx = make_ctx(bridge)
    img = make_img()
    res = bo.ImageResult(img=img, failed=False, error="", job_id="j", corr_id="c")
    assert bo.finish_image(ctx, res) == "next"
    assert img.status == "completed" and len(bridge._finished) == 1

    img2 = make_img("p2.png")
    res2 = bo.ImageResult(img=img2, failed=True, error="nope", job_id="j", corr_id="c")
    assert bo.finish_image(ctx, res2) == "next"
    assert img2.status == "failed" and img2.error == "nope"

    img3 = make_img("p3.png")
    res3 = bo.ImageResult(img=img3, failed=True, error="Cancelled by user", job_id="j", corr_id="c")
    assert bo.finish_image(ctx, res3) == "stop"
    assert img3.error == "Cancelled by user" and len(bridge._finished) == 2  # no emit

    bridge._cancel_requested = True
    img4 = make_img("p4.png")
    res4 = bo.ImageResult(img=img4, failed=False, error="", job_id="j", corr_id="c")
    assert bo.finish_image(ctx, res4) == "stop"


@pytest.mark.asyncio
async def test_finish_primary_tab_paths(monkeypatch):
    ctx = make_ctx(make_bridge())
    await bo._finish_primary_tab(ctx)  # no pool -> silent
    pool = pool_with(info("tab1"))
    bridge = make_bridge(pool=pool)
    ctx = make_ctx(bridge)

    async def _boom(fctx):
        raise RuntimeError("reset down")

    monkeypatch.setattr(bo, "finish_page_after_job", _boom)
    await bo._finish_primary_tab(ctx)
    assert any("settling stuck page" in m for m, _ in bridge._logs)

    async def _cancelled(fctx):
        raise asyncio.CancelledError()

    monkeypatch.setattr(bo, "finish_page_after_job", _cancelled)
    with pytest.raises(asyncio.CancelledError):
        await bo._finish_primary_tab(ctx)


def test_settle_stuck_only_busy_like():
    pool = pool_with(info("tab1"))
    ctx = make_ctx(make_bridge(pool=pool))
    bo._settle_stuck(ctx)  # steady -> untouched
    assert pool.get_page("tab1").status == PageStatus.STEADY
    pool.get_page("tab1").status = PageStatus.BUSY
    bo._settle_stuck(ctx)
    assert pool.get_page("tab1").status == PageStatus.STEADY
    bo._settle_stuck(make_ctx(make_bridge()))  # no pool -> silent


# ---- one image + sequential ----

@pytest.mark.asyncio
async def test_run_one_image_gates(monkeypatch):
    instant_sleep(monkeypatch)
    bridge = make_bridge()
    bridge._cancel_requested = True
    assert await bo._run_one_image(make_ctx(bridge), make_img()) == "stop"

    bridge = make_bridge()
    bridge._pause_requested = True
    bridge._cancel_requested = True
    assert await bo._run_one_image(make_ctx(bridge), make_img()) == "stop"


@pytest.mark.asyncio
async def test_run_one_image_happy(monkeypatch):
    instant_sleep(monkeypatch)
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="tab1")]
    bridge = make_bridge(urls=urls)
    ctx = make_ctx(bridge)
    img = make_img()
    assert await bo._run_one_image(ctx, img) == "next"
    assert img.status == "completed"


@pytest.mark.asyncio
async def test_run_sequential_completes_and_cancels(monkeypatch):
    instant_sleep(monkeypatch)
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="tab1")]
    bridge = make_bridge(images=[make_img("a.png"), make_img("b.png")], urls=urls)
    ctx = make_ctx(bridge, images=list(bridge.state.images))
    await bo._run_sequential(ctx)
    assert [i.status for i in bridge.state.images] == ["completed", "completed"]
    assert bridge._run_state == "running"   # S5: a pass body never writes run state (supervisor owns it)

    async def _raise(ctx, img):
        raise asyncio.CancelledError()

    monkeypatch.setattr(bo, "_run_one_image", _raise)
    settled = []
    monkeypatch.setattr(bo, "_settle_stuck", lambda ctx: settled.append(1))
    ctx.images = [make_img("c.png")]  # a fresh claim — completed ones are skipped (I-44)
    with pytest.raises(asyncio.CancelledError):
        await bo._run_sequential(ctx)
    assert settled


@pytest.mark.asyncio
async def test_sequential_skips_settled_images_at_claim_time(monkeypatch):
    """B13 / I-44: a stale run list may hold completed/skipped images — never re-sent."""
    instant_sleep(monkeypatch)
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="tab1")]
    done = make_img("done.png", "completed", True)
    done.attempt_count, done.output_path = 1, "/tmp/done_AI.png"
    skipped = make_img("skip.png", "skipped", True)
    fresh = make_img("fresh.png")
    bridge = make_bridge(images=[done, skipped, fresh], urls=urls)
    await bo._run_sequential(make_ctx(bridge, images=[done, skipped, fresh]))
    assert (done.status, done.attempt_count, done.output_path) == ("completed", 1, "/tmp/done_AI.png")
    assert (skipped.status, skipped.attempt_count) == ("skipped", 0)
    assert (fresh.status, fresh.attempt_count) == ("completed", 1)
    assert [j for j, _ in bridge._started] and len(bridge._started) == 1  # one job only
    lines = [m for m, _ in bridge._logs]
    assert "⏭ Skipping done.png — already completed" in lines
    assert "⏭ Skipping skip.png — already skipped" in lines
    assert bridge._run_state == "running"  # the skip never stalls the pass; run state is the supervisor's (S5)


@pytest.mark.asyncio
async def test_sequential_skips_an_image_deselected_mid_run(monkeypatch):
    """V1 / RULE 10: the flag the user clears during a run is part of the same predicate."""
    instant_sleep(monkeypatch)
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="tab1")]
    first, second = make_img("first.png"), make_img("second.png")
    bridge = make_bridge(images=[first, second], urls=urls)
    started = bridge.job_started.emit

    def deselect_second_on_first_start(job, path):  # the user clicks the checkbox while job 1 runs
        second.selected = False
        started(job, path)
    bridge.job_started.emit = deselect_second_on_first_start
    await bo._run_sequential(make_ctx(bridge, images=[first, second]))
    assert (first.status, second.status, second.attempt_count) == ("completed", "pending", 0)
    assert len(bridge._started) == 1
    assert ("⏭ Skipping second.png — deselected", "info") in bridge._logs


@pytest.mark.asyncio
async def test_parallel_fallback_does_not_redo_completed(monkeypatch):
    """B13 door 2: parallel dispatch dies mid-way → sequential fallback must not re-run its wins."""
    instant_sleep(monkeypatch)
    pool = pool_with(info("t1"), info("t2"))
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="t1"),
            UrlRow.create("https://arena.ai/b", enabled=True, tab_id="t2")]
    a, b = make_img("a.png"), make_img("b.png")
    bridge = make_bridge(images=[a, b], urls=urls, pool=pool)
    ctx = make_ctx(bridge, tab_id="t1", images=[a, b])

    async def _dies_after_first(bridge_, pool_, images, urls_):
        images[0].status, images[0].attempt_count = "completed", 1
        raise RuntimeError("pool went away")

    monkeypatch.setattr(bo, "dispatch_parallel", _dies_after_first)
    assert await bo._try_parallel(ctx) is False
    await bo._run_sequential(ctx)
    assert (a.status, a.attempt_count) == ("completed", 1)  # not sent a second time
    assert (b.status, b.attempt_count) == ("completed", 1)
    assert [p for j, p in bridge._started] == ["/tmp/b.png"]


# ---- prepare / parallel / gate / run ----

@pytest.mark.asyncio
async def test_prepare_batch_takes_the_pass_plan(monkeypatch):
    """S5: the tab and the scope come from the supervisor's plan (no re-snapshot, no lifecycle)."""
    import app.browser.cdp_arena as arena_mod
    from app.services.live.supervisor import PassPlan
    monkeypatch.setattr(arena_mod, "CDPArenaController", lambda *a, **k: make_ctrl())
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="tab1")]
    bridge = make_bridge(images=[make_img()], urls=urls)
    plan = PassPlan(images=list(bridge.state.images), urls=urls, allowed={"tab1"}, tab_id="tab1")
    ctx = await bo.prepare_batch(bridge, plan)
    assert ctx.tab_id == "tab1" and len(ctx.images) == 1 and ctx.allowed == {"tab1"}
    assert ctx.images is not plan.images                     # its own list
    assert any("Action blocks stack" in m for m, _ in bridge._logs)
    assert bridge._run_state == "running"


@pytest.mark.asyncio
async def test_warn_unready_branches():
    bridge = make_bridge()
    await bo._warn_unready(bridge, make_ctrl(ready=False))
    assert any("Page not ready" in m for m, _ in bridge._logs)
    await bo._warn_unready(bridge, SimpleNamespace())  # no probe -> silent


def test_load_run_settings_uses_the_plan_not_a_private_predicate():
    """S5: the scope is planned once by the supervisor (claim scope, I-49); the orchestrator copies it."""
    from app.services.live.supervisor import PassPlan
    imgs = [make_img("a.png", "pending", True), make_img("b.png", "completed", True)]
    ctx = make_ctx(make_bridge(images=imgs))
    bo._load_run_settings(ctx, PassPlan(images=[imgs[0]]))
    assert [i.relative_path for i in ctx.images] == ["a.png"]
    assert ctx.prompt_template == "draw x"
    assert not hasattr(bo, "_selected_images"), "duplicate predicate must stay deleted (RULE 16.4)"
    assert not hasattr(bo, "run_scope"), "the orchestrator no longer snapshots the scope itself (S5)"


@pytest.mark.asyncio
async def test_try_parallel_branches(monkeypatch):
    ctx = make_ctx(make_bridge(), images=[make_img(), make_img("b.png")])
    assert await bo._try_parallel(ctx) is False  # no pool

    pool = pool_with(info("t1"), info("t2"))
    urls = [UrlRow.create("https://arena.ai/a", enabled=True, tab_id="t1"),
            UrlRow.create("https://arena.ai/b", enabled=True, tab_id="t2")]
    bridge = make_bridge(images=[make_img(), make_img("b.png")], urls=urls, pool=pool)
    ctx = make_ctx(bridge, images=list(bridge.state.images))
    called = []

    async def _disp(*a):
        called.append(1)

    monkeypatch.setattr(bo, "dispatch_parallel", _disp)
    assert await bo._try_parallel(ctx) is True and called

    pool1 = pool_with(info("t1"))
    bridge1 = make_bridge(images=[make_img(), make_img("b.png")], urls=urls, pool=pool1)
    assert await bo._try_parallel(make_ctx(bridge1, images=list(bridge1.state.images))) is False
    assert any("only 1 page" in m for m, _ in bridge1._logs)

    empty = pool_with()
    bridge0 = make_bridge(images=[make_img(), make_img("b.png")], urls=urls, pool=empty)
    assert await bo._try_parallel(make_ctx(bridge0, images=list(bridge0.state.images))) is False
    assert any("Pool empty" in m for m, _ in bridge0._logs)


@pytest.mark.asyncio
async def test_batch_gate_paths():
    assert await bo._await_batch_gate(make_ctx(make_bridge())) is True
    pool = pool_with(info("tab1"))
    ctx = make_ctx(make_bridge(pool=pool))
    assert await bo._await_batch_gate(ctx) is True
    ctx.bridge._cancel_requested = True
    pool.get_page("tab1").status = PageStatus.COOLDOWN
    pool.get_page("tab1").cooldown_until = 9999999999.0
    assert await bo._await_batch_gate(ctx) is False
    assert ctx.bridge._run_state == "running"   # S5: the gate reports, the supervisor decides
