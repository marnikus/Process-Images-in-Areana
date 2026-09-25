# ideal-size: ~450 lines reason=single per-pass body owns prepare/parallel-gate/sequential sharing BatchCtx; splitting would scatter one pass flow that always changes together (RULE 18.2)
"""Batch orchestrator — one pass of the live run (A3, S5).

Owns the pass body: prepare (controller + settings + stack announce from the
supervisor's `PassPlan`), parallel-dispatch probe, pooled cooldown gates,
per-image execute/finish. Per-image block execution is delegated to
`single_job_runner.run_blocks_for_image` (the converged pipeline). It has
no lifecycle opinion: `live.supervisor.run_live` plans each pass, decides
when to wait and is the only writer of the run state (D-8).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.browser.page_pool import tab_label_of
from app.core.enums import ImageStatus
from app.core.run_scope import claim_denied
from app.services import auto_connect as ac
from app.services import firefox_job
from app.services.job_events import job_finished_payload
from app.services.job_history import note_job_started, record_batch_result
from app.services.cooldown_service import (
    FinishCtx,
    clear_tab_abort,
    finish_page_after_job,
    is_stuck_status,
    maybe_note_rate_limit,
    resolve_primary_tab,
    set_tab_image,
    wait_for_batch_ready,
    wait_for_tab_ready,
)
from app.services.multi_page_dispatcher import dispatch_parallel
from app.services.run_state import ensure_pool_page
from app.services.single_job_runner import JobCtx, run_blocks_for_image
from app.utils.correlation import build_final_prompt, generate_correlation_id


@dataclass
class BatchCtx:
    """Batch run state (keeps params ≤3, RULE 16)."""

    bridge: Any
    ctrl: Any
    urls: list = field(default_factory=list)
    allowed: set = field(default_factory=set)
    tab_id: str = ""
    images: list = field(default_factory=list)
    prompt_template: str = ""


@dataclass
class ImageResult:
    """Per-image outcome (parameter object, RULE 19)."""

    img: Any
    failed: bool
    error: str
    job_id: str
    corr_id: str
    done_msg: str = ""  # success text override — the Firefox lane downloads nothing (D-8)


def _pool_of(bridge):
    return getattr(bridge, "_page_pool", None)


def pool_summary(pool) -> str:
    """One-line pool state for run decisions (the supervisor's wait lines reuse it)."""
    try:
        pages = pool.status_snapshot().get("pages", [])
    except Exception:
        return "pool n/a"
    bits = []
    for page in pages:
        bit = f"{(page.get('tab_id') or '?')[:6]}:{page.get('status')}({'c' if page.get('is_connected') else 'd'})"
        bit += f"·j{page.get('jobs_completed', 0)}"
        if page.get("current_image"):
            bit += f"·▶{page.get('current_image')}"
        bits.append(bit)
    return ", ".join(bits) or "pool empty"


def _log_stay_reason(bridge, tab_id: str) -> None:
    """Warn when staying on an unready primary, with pool state."""
    try:
        pool = _pool_of(bridge)
        if not (pool and tab_id):
            return
        page = pool.get_page(tab_id)
        if page is None or page.is_free():
            return
        bridge._log(f"⏳ No ready tab — staying on {tab_label_of(pool, tab_id)} ({page.status}) — pool: {pool_summary(pool)}", "warn")
    except Exception:
        pass


def _pool_ws(pool, want: str) -> str:
    """Websocket URL of a pooled page (missing-safe)."""
    page = pool.get_page(want) if pool else None
    return getattr(page, "ws_url", "") or ""


async def _move_to_tab(bridge, tab_id: str, want: str) -> str:
    """Reconnect to a readier tab; stay on failure."""
    try:
        pool = _pool_of(bridge)
        if await _retarget(pool, want, bridge):
            bridge._log(f"🔀 Run moved to ready tab {want[:12]}{_move_note(pool, want)}", "info")
            return want
        bridge._log(f"⚠ Reconnect to ready tab {want[:12]} failed — staying on {(tab_id or '?')[:12]} — pool: {pool_summary(pool)}", "warn")
    except Exception as e:
        bridge._log(f"⚠ Primary move failed ({e}) — pool: {pool_summary(_pool_of(bridge))}", "warn")
    return tab_id


async def _retarget(pool, want: str, bridge) -> bool:
    """True = the run now lives on `want`: firefox's window is already up (D-9), else a fresh CDP connect."""
    page = pool.get_page(want) if pool else None
    if page is not None and getattr(page, "browser", "") == "firefox":
        return True
    ws = _pool_ws(pool, want)
    return bool(ws and bridge.cdp and await bridge.cdp.connect(ws))


def _move_note(pool, want: str) -> str:
    """The moved-line's suffix for a transportless tab (D-9)."""
    page = pool.get_page(want) if pool else None
    if page is not None and getattr(page, "browser", "") == "firefox":
        return " (firefox — no socket to reconnect)"
    return ""


async def resolve_and_claim_tab(bridge, tab_id: str, allowed) -> str:
    """Prefer a ready pooled tab owned by a checked row (I-33)."""
    try:
        want = resolve_primary_tab(_pool_of(bridge), tab_id, allowed)
    except Exception:
        return tab_id
    if not want:
        return ""
    if want == tab_id:
        _log_stay_reason(bridge, tab_id)
        return tab_id
    return await _move_to_tab(bridge, tab_id, want)


def should_continue(ctx: BatchCtx, img: Any) -> bool:
    """Cancel/stop-after gates at the top of each image."""
    bridge = ctx.bridge
    if getattr(bridge, "_cancel_requested", False):
        bridge._log("Batch cancelled", "warn")
        return False
    if getattr(bridge, "_stop_after", False):
        bridge._log("Stopping after current as requested", "warn")
        return False
    return True


async def await_pause_or_abort(ctx: BatchCtx) -> bool:
    """Pause loop; True when the batch must stop (RULE 7)."""
    bridge = ctx.bridge
    while getattr(bridge, "_pause_requested", False):
        bridge._log("Paused, waiting for resume...", "warn")
        await asyncio.sleep(1)
        if getattr(bridge, "_cancel_requested", False):
            break
    if getattr(bridge, "_cancel_requested", False):
        bridge._log("Batch cancelled after pause", "warn")
        return True
    return False


async def _claim_tab(ctx: BatchCtx) -> bool:
    """Refresh the run tab per image; False when none usable."""
    tab_id = await resolve_and_claim_tab(ctx.bridge, ctx.tab_id, ctx.allowed)
    if not tab_id:
        ctx.bridge._log("❌ No usable checked tab left in pool — stopping batch", "error")
        return False
    ctx.tab_id = tab_id
    return True


async def await_cooldown_if_pooled(ctx: BatchCtx) -> bool:
    """Single-page cooldown gate; False only on cancel (RULE 7)."""
    bridge = ctx.bridge
    try:
        if _pool_of(bridge) and ctx.tab_id:
            await ensure_pool_page(bridge, ctx.tab_id)
            ready = await wait_for_tab_ready(_pool_of(bridge), ctx.tab_id, bridge)
            if not ready and getattr(bridge, "_cancel_requested", False):
                return False
    except Exception as e:
        bridge._log(f"Cooldown gate skipped: {e}", "warn")
    return True


def _start_tab_image(ctx: BatchCtx, img: Any) -> None:
    """Record the image on its tab; drop any stale stop request."""
    try:
        import os
        pool = _pool_of(ctx.bridge)
        clear_tab_abort(pool, ctx.tab_id)
        set_tab_image(pool, ctx.tab_id, os.path.basename(img.relative_path or ""))
        ctx.bridge._emit_pool_status()
    except Exception:
        pass


def mark_processing(ctx: BatchCtx, img: Any):
    """Claim the image for this tab (row never re-bound, I-33)."""
    url_row = ac.pick_url_for_tab(ctx.urls, ctx.tab_id)
    img.assigned_url_id = url_row.id if url_row else None
    img.attempt_count += 1
    img.status = ImageStatus.PROCESSING.value
    ctx.bridge.state.recalculate_progress()
    ctx.bridge._save_arena()
    _start_tab_image(ctx, img)
    return url_row


def build_job_ids(ctx: BatchCtx, img: Any, url_row) -> tuple:
    """Correlation/job ids + final prompt; announces the job (RULE 2)."""
    corr_id = generate_correlation_id()
    final_prompt = build_final_prompt(corr_id, ctx.prompt_template)
    url = url_row.url if url_row else "N/A"
    ctx.bridge._log(f"[{corr_id}] Starting {img.relative_path} with URL {url}", "info")
    try:
        ctx.bridge.job_started.emit(corr_id, img.absolute_path)
    except Exception:
        pass
    note_job_started(ctx.bridge, corr_id)
    return corr_id, corr_id, final_prompt


def _ff_page(ctx: BatchCtx):
    """The run tab's pool page when it is Firefox (D-9), else None."""
    try:
        pool = _pool_of(ctx.bridge)
        page = pool.get_page(ctx.tab_id) if pool and ctx.tab_id else None
    except Exception:
        return None
    return page if page is not None and getattr(page, "browser", "") == "firefox" else None


async def _execute_image(ctx: BatchCtx, img: Any, url_row) -> ImageResult:
    """Build ids, run the browser's executor (blocks or macro), wrap the outcome."""
    if _ff_page(ctx) is not None:
        return await _execute_firefox(ctx, img, url_row)
    corr_id, job_id, final_prompt = build_job_ids(ctx, img, url_row)
    job_ctx = JobCtx(bridge=ctx.bridge, ctrl=ctx.ctrl, client=ctx.bridge.cdp,
                     tab_id=ctx.tab_id, img=img, urls=ctx.urls, job_id=job_id,
                     corr_id=corr_id, final_prompt=final_prompt)
    failed, error, _src, _data = await run_blocks_for_image(job_ctx)
    return ImageResult(img=img, failed=failed, error=error, job_id=job_id, corr_id=corr_id)


async def _execute_firefox(ctx: BatchCtx, img: Any, url_row) -> ImageResult:
    """The sequential lane's Firefox branch: one macro run, same ids/history (D-9)."""
    corr_id, job_id, _final = build_job_ids(ctx, img, url_row)
    failed, error = await firefox_job.run_macro_job(
        ctx.bridge, _pool_of(ctx.bridge), ctx.tab_id)
    return ImageResult(img=img, failed=failed, error=error, job_id=job_id,
                       corr_id=corr_id, done_msg="" if failed else "Ui.Vision macro ok")


def _emit_job_finished(bridge, res: ImageResult) -> None:
    """job_finished signal, derived from the result (cancelled never emit)."""
    try:
        import json
        if res.failed:
            status, message = "failed", res.error
        else:
            status, message = "completed", (res.done_msg or f"Saved to {res.img.output_path}")
        payload = json.dumps(job_finished_payload(res.img, status, message), ensure_ascii=False)
        bridge.job_finished.emit(res.job_id, payload)
    except Exception:
        pass


def _fail_cancelled(ctx: BatchCtx, res: ImageResult) -> None:
    """Cancelled image: failed, saved, batch stops (no job_finished)."""
    res.img.status = ImageStatus.FAILED.value
    res.img.error = "Cancelled by user"
    ctx.bridge._log(f"[{res.corr_id}] ❌ Cancelled — aborting batch", "warn")
    ctx.bridge.state.recalculate_progress()
    ctx.bridge._save_arena()


def _fail_job(ctx: BatchCtx, res: ImageResult) -> None:
    """Failed image: failed + finished signal."""
    res.img.status = ImageStatus.FAILED.value
    res.img.error = res.error
    ctx.bridge._log(f"[{res.corr_id}] ❌ Failed {res.img.relative_path}: {res.error}", "error")
    _emit_job_finished(ctx.bridge, res)


def _complete_job(ctx: BatchCtx, res: ImageResult) -> None:
    """Completed image: completed + finished signal."""
    if res.img.status != ImageStatus.COMPLETED.value:
        res.img.status = ImageStatus.COMPLETED.value
    ctx.bridge._log(f"[{res.corr_id}] ✅ Job completed {res.img.relative_path}", "success")
    _emit_job_finished(ctx.bridge, res)


def _settle_image(ctx: BatchCtx, res: ImageResult) -> None:
    """Post-image: recalc/save, rate-limit note, finish page."""
    ctx.bridge.state.recalculate_progress()
    ctx.bridge._save_arena()
    if res.failed and res.error:
        maybe_note_rate_limit(_pool_of(ctx.bridge), ctx.tab_id, ctx.bridge, res.error)


def _finish_ctx_for(pool, ctx: BatchCtx) -> FinishCtx:
    """Finish with this tab's transport — a Firefox page has no CDP reset (D-8)."""
    if _ff_page(ctx) is not None:
        return FinishCtx(pool=pool, bridge=ctx.bridge, tab_id=ctx.tab_id, ctrl=None, client=None)
    return FinishCtx(pool=pool, bridge=ctx.bridge, tab_id=ctx.tab_id, ctrl=ctx.ctrl, client=ctx.bridge.cdp)


async def _finish_primary_tab(ctx: BatchCtx) -> None:
    """Post-job reset + cooldown; settles a stuck page when finish fails."""
    try:
        pool = _pool_of(ctx.bridge)
        if not (pool and ctx.tab_id):
            return
        await finish_page_after_job(_finish_ctx_for(pool, ctx))
        set_tab_image(pool, ctx.tab_id, None)
        ctx.bridge._emit_pool_status()
    except asyncio.CancelledError:
        _settle_stuck(ctx)
        raise
    except Exception as e:
        ctx.bridge._log(f"Post-job reset/cooldown skipped: {e} — settling stuck page", "warn")
        _settle_stuck(ctx)


def _settle_stuck(ctx: BatchCtx) -> None:
    """Best-effort steady for a busy-like page; cooling untouched."""
    try:
        pool = _pool_of(ctx.bridge)
        if not (pool and ctx.tab_id):
            return
        page = pool.get_page(ctx.tab_id)
        if page is not None and is_stuck_status(page.status):
            pool.mark_steady(ctx.tab_id)
    except Exception:
        pass


def finish_image(ctx: BatchCtx, res: ImageResult) -> str:
    """Record the outcome; 'stop' ends the batch, else 'next'."""
    if getattr(ctx.bridge, "_cancel_requested", False) or (res.failed and "Cancelled" in (res.error or "")):
        _fail_cancelled(ctx, res)
        return "stop"
    if res.failed:
        _fail_job(ctx, res)
    else:
        _complete_job(ctx, res)
    _settle_image(ctx, res)
    record_batch_result(ctx, res)  # the history row for this job_finished (cancelled return above)
    return "next"


async def _run_one_image(ctx: BatchCtx, img: Any) -> str:
    """One image: gates → claim → execute → finish ('stop' ends batch)."""
    if not should_continue(ctx, img):
        return "stop"
    if await await_pause_or_abort(ctx):
        return "stop"
    if not await _claim_tab(ctx):
        return "stop"
    if not await await_cooldown_if_pooled(ctx):
        return "stop"
    res = await _execute_image(ctx, img, mark_processing(ctx, img))
    done = finish_image(ctx, res)
    if done == "next":
        await _finish_primary_tab(ctx)
        await asyncio.sleep(1)
    return done


async def _run_sequential(ctx: BatchCtx) -> None:
    """Per-image loop (settled images skipped at claim time, I-44); cancel settles the tab."""
    try:
        for img in ctx.images:
            if claim_denied(img, ctx.bridge._log):
                continue
            if await _run_one_image(ctx, img) == "stop":
                break
    except asyncio.CancelledError:
        _settle_stuck(ctx)
        raise


async def _warn_unready(bridge, ctrl) -> None:
    """Page-readiness probe; warns but never blocks the batch."""
    try:
        ready, reasons = await ctrl.is_page_ready()
    except Exception:
        return
    if not ready:
        bridge._log(f"⚠ Page not ready: {', '.join(reasons)} — trying anyway", "warn")


def _load_run_settings(ctx: BatchCtx) -> None:
    """Prompt template for this pass (the images came with the plan)."""
    ctx.prompt_template = ctx.bridge.state.prompt.get("user_prompt", "")


def _announce_stack(ctx: BatchCtx) -> None:
    """Emit + log the action-block stack for this batch."""
    stack = ctx.bridge._get_action_blocks()
    ctx.bridge._emit_action_blocks()
    head = ", ".join(f"{b.display_name}({'ON' if b.enabled else 'OFF'})" for b in stack[:6])
    ctx.bridge._log(f"📦 Action blocks stack: {len(stack)} blocks — {head}{'...' if len(stack) > 6 else ''}", "info")


async def prepare_batch(bridge, plan) -> BatchCtx:
    """Controller + settings + stack announce from the supervisor's plan (no re-snapshot)."""
    from app.browser.cdp_arena import CDPArenaController
    ctrl = CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
    await _warn_unready(bridge, ctrl)
    ctx = BatchCtx(bridge=bridge, ctrl=ctrl, urls=list(plan.urls), allowed=set(plan.allowed),
                   tab_id=plan.tab_id, images=list(plan.images))
    _load_run_settings(ctx)
    _announce_stack(ctx)
    return ctx


def _log_parallel_fallback(ctx: BatchCtx, total: int) -> None:
    """Why this batch stays sequential (1 page or pool empty)."""
    if total == 1:
        ctx.bridge._log("ℹ Pool has only 1 page — connect 2nd tab via Page Pool → Add Selected Tab or URL LIST Connect for parallel. Running sequentially on 1 page.", "warn")
    elif total == 0:
        ctx.bridge._log("ℹ Pool empty — using primary CDP connection single mode. Connect tabs to enable parallel.", "info")


async def _try_parallel(ctx: BatchCtx) -> bool:
    """Parallel (feeder) dispatch whenever 2+ checked pages exist — any image count (B-3); else sequential."""
    try:
        pool = _pool_of(ctx.bridge)
        if not pool:
            return False
        total, free = ac.counts_in(pool, ctx.allowed)
        if total >= 2 and free >= 1:
            ctx.bridge._log(f"🚀 Parallel mode: {total} pages {free} free, {len(ctx.images)} images — dispatching to different pages steady/busy tracked, no double-send", "success")
            ctx.bridge._emit_pool_status()
            await dispatch_parallel(ctx.bridge, pool, ctx.images, ctx.urls)
            return True
        _log_parallel_fallback(ctx, total)
    except Exception as e:
        ctx.bridge._log(f"Parallel dispatch check failed {e}, fallback to single", "warn")
    return False


async def _await_batch_gate(ctx: BatchCtx) -> bool:
    """Batch-start gate: pooled tabs steady before the first job."""
    try:
        pool = _pool_of(ctx.bridge)
        if pool and ctx.tab_id:
            await ensure_pool_page(ctx.bridge, ctx.tab_id)
            if not await wait_for_batch_ready(pool, [ctx.tab_id], ctx.bridge):
                ctx.bridge._log("Batch start aborted during cooldown wait", "warn")
                return False
    except Exception as e:
        ctx.bridge._log(f"Batch-start cooldown wait skipped: {e}", "warn")
    return True


async def run_pass(bridge, plan) -> None:
    """One pass: prepare → parallel? → gate → sequential (the supervisor owns the loop)."""
    ctx = await prepare_batch(bridge, plan)
    if await _try_parallel(ctx):
        return
    if not await _await_batch_gate(ctx):
        return
    await _run_sequential(ctx)
