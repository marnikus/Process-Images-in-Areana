"""Multi-page dispatcher — parallel dispatch to different webpages."""
# ideal-size: ~395 lines reason=single dispatch flow owns acquire/run/finish/settle helpers sharing PageJobCtx/ResultCtx/FreeWaitSpec; splitting would scatter one per-image lifecycle across files that always change together (RULE 18.2)

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.browser.page_pool import PagePool
from app.core.enums import ImageStatus
from app.core.models import ImageItem, UrlRow
from app.utils.correlation import build_final_prompt, generate_correlation_id

from . import auto_connect as ac
from .cooldown_service import FinishCtx, cooldown_aware_timeout, finish_page_after_job, is_stuck_status
from .single_job_runner import JobCtx, capture_baseline, run_blocks_for_image

log = logging.getLogger("arena")

_WAIT_POLL_SEC = 0.5


@dataclass
class DispatchCtx:
    bridge: object
    pool: PagePool
    urls: List[UrlRow]
    sem: asyncio.Semaphore
    allowed: set = field(default_factory=set)  # tab ids owned by checked rows (I-33)


@dataclass
class PageJobCtx:
    bridge: object
    pool: PagePool
    img: ImageItem
    urls: List[UrlRow]
    tab_id: str
    ctrl: object
    client: object


@dataclass
class ResultCtx:
    bridge: object
    pool: PagePool
    img: ImageItem
    tab_id: str
    corr_id: str
    job_id: str
    failed: bool
    err: str


@dataclass
class FinishInfo:
    job_id: str
    img: ImageItem
    status: str
    message: str


@dataclass
class LogInfo:
    corr_id: str
    tab_id: str
    img: ImageItem
    ok: bool
    err: str


def _recalc_save(bridge):
    try:
        bridge.state.recalculate_progress()
        bridge._save_arena()
    except Exception:
        pass


def _mark_steady_emit(pool, bridge, tab_id):
    try:
        pool.mark_steady(tab_id)
        bridge._emit_pool_status()
        bridge._log(f"✅ Page {tab_id[:12]} STEADY ready", "success")
    except Exception:
        pass


def _settle_stuck_emit(pool, bridge, tab_id):
    """Steady a busy-like page after failure; a started cooldown survives."""
    try:
        page = pool.get_page(tab_id)
    except Exception:
        return
    try:
        if page is not None and is_stuck_status(page.status):
            _mark_steady_emit(pool, bridge, tab_id)
    except Exception:
        pass


async def _wait_pause(bridge):
    while getattr(bridge, "_pause_requested", False):
        await asyncio.sleep(1)
        if bridge._cancel_requested:
            break


def _acquire_free_in(pool, allowed: set, job_id: str):
    """Lock-guarded acquire of a free page inside the checked-tab set (I-33).

    External-lock pattern (same as sync_pool_presence): PagePool keeps its
    15-method cap, dispatch keeps the gating decision."""
    try:
        with pool._lock:
            for p in pool._pages.values():
                p.try_expire()
            free = [p for p in pool._pages.values()
                    if p.is_free() and p.tab_id in (allowed or set())]
            if not free:
                return None
            page = min(free, key=lambda p: p.jobs_completed)
    except AttributeError:
        return None
    pool.mark_busy(page.tab_id, job_id)
    return page


@dataclass
class FreeWaitSpec:
    """Wait inputs for one checked free page (keeps params ≤4, RULE 16)."""

    pool: object
    allowed: set
    job_id: str
    timeout_sec: float
    cancel_check: object = None


async def _wait_free_in(spec: FreeWaitSpec):
    """Wait for a checked free page; cancel and timeout bounded (RULE 7)."""
    loop = asyncio.get_event_loop()
    start = loop.time()
    while True:
        if spec.cancel_check and spec.cancel_check():
            return None
        got = _acquire_free_in(spec.pool, spec.allowed, spec.job_id)
        if got:
            return got
        if loop.time() - start > spec.timeout_sec:
            return None
        await asyncio.sleep(_WAIT_POLL_SEC)


async def _acquire_page(pool, bridge, job_id: str, allowed: set):
    """One gate for both wait styles: only tabs owned by checked rows."""
    spec = FreeWaitSpec(pool=pool, allowed=allowed, job_id=job_id,
                        timeout_sec=cooldown_aware_timeout(pool),
                        cancel_check=lambda: bridge._cancel_requested)
    return await _wait_free_in(spec)


def _get_clients(pool, tab_id) -> Tuple[object, object]:
    try:
        client, ctrl = pool.get_clients(tab_id)
        return ctrl, client
    except Exception:
        return None, None


async def prepare_image_for_job(bridge, img, urls, tab_id: str):
    """Record the tab's own checked row on the image (never re-links rows)."""
    url_row = ac.pick_url_for_tab(urls, tab_id)
    img.assigned_url_id = url_row.id if url_row else None
    img.attempt_count += 1
    img.status = ImageStatus.PROCESSING.value
    _recalc_save(bridge)
    corr = generate_correlation_id()
    tmpl = bridge.state.prompt.get("user_prompt", "")
    final = build_final_prompt(corr, tmpl)
    return url_row, corr, corr, final


async def _run_image_job(ctx: PageJobCtx):
    url_row, corr_id, job_id, final_prompt = await prepare_image_for_job(
        ctx.bridge, ctx.img, ctx.urls, ctx.tab_id)
    try:
        ctx.bridge.job_started.emit(job_id, ctx.img.absolute_path)
    except Exception:
        pass
    baseline = await capture_baseline(ctx.ctrl)
    job_ctx = JobCtx(bridge=ctx.bridge, ctrl=ctx.ctrl, client=ctx.client, tab_id=ctx.tab_id, img=ctx.img, urls=ctx.urls, job_id=job_id, corr_id=corr_id, final_prompt=final_prompt, baseline=baseline)
    failed, err, _, _ = await run_blocks_for_image(job_ctx)
    return url_row, corr_id, job_id, failed, err


def _handle_result(ctx: ResultCtx):
    if ctx.bridge._cancel_requested:
        ctx.img.status = ImageStatus.FAILED.value
        ctx.img.error = "Cancelled"
        _recalc_save(ctx.bridge)
        return
    if ctx.failed:
        ctx.img.status = ImageStatus.FAILED.value
        ctx.img.error = ctx.err
        _emit_finished(ctx.bridge, FinishInfo(job_id=ctx.job_id, img=ctx.img, status="failed", message=ctx.err))
        _log_result(ctx.bridge, LogInfo(corr_id=ctx.corr_id, tab_id=ctx.tab_id, img=ctx.img, ok=False, err=ctx.err))
    else:
        if ctx.img.status != ImageStatus.COMPLETED.value:
            ctx.img.status = ImageStatus.COMPLETED.value
        _emit_finished(ctx.bridge, FinishInfo(job_id=ctx.job_id, img=ctx.img, status="completed", message=f"Saved {ctx.img.output_path}"))
        _log_result(ctx.bridge, LogInfo(corr_id=ctx.corr_id, tab_id=ctx.tab_id, img=ctx.img, ok=True, err=""))
    _recalc_save(ctx.bridge)


def _emit_finished(bridge, info: FinishInfo):
    try:
        payload = json.dumps({"status": info.status, "message": info.message, "output_path": info.img.output_path or ""}, ensure_ascii=False)
        bridge.job_finished.emit(info.job_id, payload)
    except Exception:
        pass


def _log_result(bridge, info: LogInfo):
    try:
        if info.ok:
            bridge._log(f"[{info.corr_id}] [Page {info.tab_id[:6]}] ✅ {info.img.relative_path}", "success")
        else:
            bridge._log(f"[{info.corr_id}] [Page {info.tab_id[:6]}] ❌ {info.img.relative_path}: {info.err}", "error")
    except Exception:
        pass


def _emit_status_safe(bridge):
    try:
        bridge._emit_pool_status()
    except Exception:
        pass


def _start_tab_image(pool, tab_id, img):
    """Record the image on its tab; drop any stale stop request."""
    try:
        import os
        from .cooldown_service import clear_tab_abort, set_tab_image
        clear_tab_abort(pool, tab_id)
        set_tab_image(pool, tab_id, os.path.basename(img.relative_path or ""))
    except Exception:
        pass


def _clear_tab_image(pool, tab_id):
    """Forget the finished image (pool emit follows in finish)."""
    try:
        from .cooldown_service import set_tab_image
        set_tab_image(pool, tab_id, None)
    except Exception:
        pass


async def _finish_page_safely(finish_ctx: FinishCtx) -> None:
    """Finish the page after the job; always settle the stuck-emit on error."""
    try:
        await finish_page_after_job(finish_ctx)
    except asyncio.CancelledError:
        _settle_stuck_emit(finish_ctx.pool, finish_ctx.bridge, finish_ctx.tab_id)
        raise
    except Exception:
        _settle_stuck_emit(finish_ctx.pool, finish_ctx.bridge, finish_ctx.tab_id)


async def run_one_image_on_page(bridge, pool, img, urls):
    if bridge._cancel_requested:
        return
    allowed = ac.enabled_tab_ids(urls)
    free_page = await _acquire_page(pool, bridge, img.id, allowed)
    if not free_page:
        _log_no_free(bridge, img)
        return
    _emit_status_safe(bridge)
    tab_id = free_page.tab_id
    ctrl, client = _get_clients(pool, tab_id)
    if not ctrl or not client:
        _log_no_ctrl(bridge, tab_id)
        _mark_steady_emit(pool, bridge, tab_id)
        return
    _log_assign(bridge, img, tab_id, free_page)
    _start_tab_image(pool, tab_id, img)
    try:
        url_row, corr_id, job_id, failed, err = await _run_image_job(PageJobCtx(bridge=bridge, pool=pool, img=img, urls=urls, tab_id=tab_id, ctrl=ctrl, client=client))
        _handle_result(ResultCtx(bridge=bridge, pool=pool, img=img, tab_id=tab_id, corr_id=corr_id, job_id=job_id, failed=failed, err=err))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        _handle_exception(bridge, img, tab_id, e)
    finally:
        _clear_tab_image(pool, tab_id)
        finish_ctx = FinishCtx(pool=pool, bridge=bridge, tab_id=tab_id, ctrl=ctrl, client=client)
        await _finish_page_safely(finish_ctx)


def _log_no_free(bridge, img):
    try:
        bridge._log(f"⏰ No free page for {img.relative_path}", "warn")
    except Exception:
        pass


def _log_no_ctrl(bridge, tab_id):
    try:
        bridge._log(f"⚠ No controller {tab_id[:12]}", "warn")
    except Exception:
        pass


def _log_assign(bridge, img, tab_id, free_page):
    try:
        title = getattr(free_page, "title", "")[:20]
        bridge._log(f"📤 {img.relative_path} -> page {tab_id[:12]} {title} BUSY", "info")
    except Exception:
        pass


def _handle_exception(bridge, img, tab_id, e):
    try:
        bridge._log(f"❌ {img.relative_path} on {tab_id[:6]} failed: {e}", "error")
    except Exception:
        pass
    try:
        img.status = ImageStatus.FAILED.value
        img.error = str(e)
        _recalc_save(bridge)
    except Exception:
        pass


async def dispatch_parallel(bridge, pool, images, urls):
    if not pool or not images:
        return
    allowed = ac.enabled_tab_ids(urls)
    if not allowed:
        try:
            bridge._log("⚠ Parallel dispatch skipped — no checked URL owns a tab", "warn")
        except Exception:
            pass
        return
    total, _ = ac.counts_in(pool, allowed)
    sem = asyncio.Semaphore(max(1, total))
    ctx = DispatchCtx(bridge=bridge, pool=pool, urls=urls, sem=sem, allowed=allowed)
    tasks = await _create_tasks(ctx, images)
    await _await_tasks(bridge, tasks)
    _finalize_batch(bridge)


async def _create_tasks(ctx: DispatchCtx, images):
    tasks = []
    for img in images:
        if ctx.bridge._cancel_requested:
            break
        if getattr(ctx.bridge, "_stop_after", False):
            break
        await _wait_pause(ctx.bridge)
        if ctx.bridge._cancel_requested:
            break
        t = asyncio.create_task(_run_with_sem(ctx, img))
        tasks.append(t)
        await asyncio.sleep(0.2)
    return tasks


async def _run_with_sem(ctx: DispatchCtx, img):
    async with ctx.sem:
        await run_one_image_on_page(ctx.bridge, ctx.pool, img, ctx.urls)


async def _await_tasks(bridge, tasks):
    if not tasks:
        return
    try:
        bridge._log(f"⏳ Waiting {len(tasks)} tasks steady/busy tracked", "info")
    except Exception:
        pass
    await asyncio.gather(*tasks, return_exceptions=True)


def _finalize_batch(bridge):
    try:
        bridge._log("🏁 Parallel batch complete steady", "success")
        bridge._run_state = "idle"
        bridge._emit_arena_state()
        bridge._emit_pool_status()
    except Exception:
        pass
