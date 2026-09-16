"""Multi-page dispatcher — parallel dispatch to different webpages."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.browser.page_pool import PagePool
from app.core.enums import ImageStatus
from app.core.models import ImageItem, UrlRow
from app.utils.correlation import build_final_prompt, generate_correlation_id

from .single_job_runner import JobCtx, capture_baseline, run_blocks_for_image

log = logging.getLogger("arena")


@dataclass
class DispatchCtx:
    bridge: object
    pool: PagePool
    urls: List[UrlRow]
    sem: asyncio.Semaphore


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


def _pick_enabled_url(urls: List[UrlRow]) -> Optional[UrlRow]:
    if not urls:
        return None
    for u in urls:
        if u.enabled:
            return u
    return urls[0]


def _recalc_save(bridge):
    try:
        bridge.state.recalculate_progress()
        bridge._save_arena()
    except Exception:
        pass


def _mark_busy_emit(pool, bridge, tab_id, job_id):
    try:
        pool.mark_busy(tab_id, job_id)
        bridge._emit_pool_status()
    except Exception:
        pass


def _mark_steady_emit(pool, bridge, tab_id):
    try:
        # check if cooldown expired first
        try:
            if hasattr(pool, "check_cooldowns"):
                pool.check_cooldowns()
        except Exception:
            pass
        pool.mark_steady(tab_id)
        bridge._emit_pool_status()
        try:
            p = pool.get_page(tab_id)
            if p and p.is_in_cooldown():
                rem = p.remaining_cooldown()
                bridge._log(f"⏳ Page {tab_id[:12]} COOLDOWN {rem}s", "info")
            else:
                bridge._log(f"✅ Page {tab_id[:12]} STEADY ready", "success")
        except Exception:
            bridge._log(f"✅ Page {tab_id[:12]} STEADY ready", "success")
    except Exception:
        pass


def _get_page_url(bridge, tab_id) -> str:
    try:
        if hasattr(bridge, "_page_pool") and bridge._page_pool:
            page = bridge._page_pool.get_page(tab_id)
            return getattr(page, "url", "") if page else ""
    except Exception:
        pass
    return ""


def _find_url_row_for_tab(bridge, tab_id, urls):
    try:
        page_url = _get_page_url(bridge, tab_id)
        if page_url:
            for u in urls:
                if page_url in u.url or u.url in page_url:
                    return u
        for u in urls:
            if u.enabled:
                return u
    except Exception:
        pass
    return None


async def _wait_pause(bridge):
    while getattr(bridge, "_pause_requested", False):
        await asyncio.sleep(1)
        if bridge._cancel_requested:
            break


async def _get_free_page(pool, bridge, job_id: str):
    try:
        return await pool.wait_for_free_page(timeout_sec=600, cancel_check=lambda: bridge._cancel_requested, job_id=job_id)
    except TypeError:
        # fallback old signature
        return await pool.wait_for_free_page(timeout_sec=600, cancel_check=lambda: bridge._cancel_requested)


def _get_clients(pool, tab_id) -> Tuple[object, object]:
    try:
        client, ctrl = pool.get_clients(tab_id)
        return ctrl, client
    except Exception:
        return None, None


async def _acquire_page(pool, bridge, job_id: str):
    try:
        return await pool.wait_for_free_page(timeout_sec=600, cancel_check=lambda: bridge._cancel_requested, job_id=job_id)
    except TypeError:
        try:
            if hasattr(pool, "acquire_free_page"):
                start = asyncio.get_event_loop().time()
                while True:
                    if bridge._cancel_requested:
                        return None
                    p = await pool.acquire_free_page(job_id)
                    if p:
                        return p
                    if asyncio.get_event_loop().time() - start > 600:
                        return None
                    await asyncio.sleep(0.5)
        except Exception:
            pass
        return await pool.wait_for_free_page(timeout_sec=600, cancel_check=lambda: bridge._cancel_requested)


async def prepare_image_for_job(bridge, img, urls):
    url_row = _pick_enabled_url(urls)
    img.assigned_url_id = url_row.id if url_row else None
    img.attempt_count += 1
    img.status = ImageStatus.PROCESSING.value
    _recalc_save(bridge)
    corr = generate_correlation_id()
    tmpl = bridge.state.prompt.get("user_prompt", "")
    final = build_final_prompt(corr, tmpl)
    return url_row, corr, corr, final


async def _run_image_job(ctx: PageJobCtx):
    url_row, corr_id, job_id, final_prompt = await prepare_image_for_job(ctx.bridge, ctx.img, ctx.urls)
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


async def _get_free_or_acquire(pool, bridge, img):
    free_page = await _acquire_page(pool, bridge, img.id)
    if free_page:
        _emit_status_safe(bridge)
        return free_page
    free_page = await _get_free_page(pool, bridge, img.id)
    if free_page:
        _mark_busy_emit(pool, bridge, free_page.tab_id, img.id)
    return free_page


def _ensure_pool_cooldowns(pool):
    try:
        if hasattr(pool, "check_cooldowns"):
            pool.check_cooldowns()
    except Exception:
        pass


@dataclass
class CycleRunCtx:
    bridge: object
    pool: object
    tab_id: str
    img: object
    urls: list
    ctrl: object
    client: object
    url_row_for_tab: object


async def _run_job_with_cycle(ctx: CycleRunCtx):
    url_row, corr_id, job_id, failed, err = await _run_image_job(
        PageJobCtx(bridge=ctx.bridge, pool=ctx.pool, img=ctx.img, urls=ctx.urls, tab_id=ctx.tab_id, ctrl=ctx.ctrl, client=ctx.client)
    )
    _handle_result(ResultCtx(bridge=ctx.bridge, pool=ctx.pool, img=ctx.img, tab_id=ctx.tab_id, corr_id=corr_id, job_id=job_id, failed=failed, err=err))
    try:
        from .job_cycle_service import JobCycleCtx, handle_job_completed_cycle

        cctx = JobCycleCtx(bridge=ctx.bridge, pool=ctx.pool, tab_id=ctx.tab_id, url_row=ctx.url_row_for_tab or url_row, controller=ctx.ctrl)
        await handle_job_completed_cycle(cctx)
    except Exception as e:
        try:
            ctx.bridge._log(f"Cycle handling failed {e}", "warn")
        except Exception:
            pass
    return url_row


async def run_one_image_on_page(bridge, pool, img, urls):
    if bridge._cancel_requested:
        return
    _ensure_pool_cooldowns(pool)
    free_page = await _get_free_or_acquire(pool, bridge, img)
    if not free_page:
        _log_no_free(bridge, img)
        return
    tab_id = free_page.tab_id
    ctrl, client = _get_clients(pool, tab_id)
    if not ctrl or not client:
        _log_no_ctrl(bridge, tab_id)
        _mark_steady_emit(pool, bridge, tab_id)
        return
    _log_assign(bridge, img, tab_id, free_page)
    url_row_for_tab = _find_url_row_for_tab(bridge, tab_id, urls)
    try:
        await _run_job_with_cycle(CycleRunCtx(bridge=bridge, pool=pool, tab_id=tab_id, img=img, urls=urls, ctrl=ctrl, client=client, url_row_for_tab=url_row_for_tab))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        _handle_exception(bridge, img, tab_id, e)
    finally:
        _mark_steady_emit(pool, bridge, tab_id)


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
    try:
        total, _ = pool.get_counts()
    except Exception:
        total = len(getattr(pool, "_pages", {}))
    sem = asyncio.Semaphore(max(1, total))
    ctx = DispatchCtx(bridge=bridge, pool=pool, urls=urls, sem=sem)
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
