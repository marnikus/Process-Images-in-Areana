"""Batch orchestrator — the run-batch pipeline (W1.5).

Verbatim port of Bridge._do_run_batch (1,209 LOC, CC 356) into small
named functions. Mapping rules kept bug-for-bug (RULE 8 goldens in
tests/characterization/test_run_batch_goldens.py):
- ``self``      -> ``run.bridge`` (b in tight helpers)
- per-image locals (baseline/new_src/file_bytes/...) -> ``job`` (JobState)
- the block elif-ladder -> ``_BLOCK_HANDLERS`` dispatch table
- the repeated reload+recapture web -> ``_reload_and_recapture``
Inner-loop ``break``/``continue`` that targeted a family loop (wait
cycles / download cycles) are returned as ``BREAK``/``CONTINUE`` strings
and interpreted by that family's own loop; no branch ever targeted the
block loop directly (AST-audited before extraction).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.browser.cdp_arena import CDPArenaController
from app.browser.probe_selectors import send_click_primary, send_presence_selector, textarea_primary
from app.browser.probe_requests import HighlightSpec
from app.browser.visual_click import ClickRequest, find_and_click
from app.core.enums import ImageStatus
from app.core.naming import atomic_write_bytes, get_output_path
from app.services.auto_connect import counts_in, enabled_tab_ids, pick_url_for_tab
from app.services.cooldown_service import wait_for_batch_ready
from app.utils.correlation import build_final_prompt, generate_correlation_id

BREAK = "break"        # family-loop signal: exit the (wait/dl/image) loop
CONTINUE = "continue"  # family-loop signal: next iteration of that loop


@dataclass
class JobState:
    """Per-image locals shared across block handlers (was: loop locals)."""
    img: Any
    correlation_id: str
    job_id: str
    final_prompt: str
    baseline: Optional[Dict[str, Any]] = None
    original_old_srcs: List[str] = field(default_factory=list)
    original_old_outputs: List[Any] = field(default_factory=list)
    new_src: Optional[str] = None
    file_bytes: Optional[bytes] = None
    ctype: Optional[str] = None
    output_path: Optional[Path] = None
    ext: Optional[str] = None
    job_failed: bool = False
    job_error: str = ""
    wait_timeout: Optional[int] = None  # set by WAIT block, read by DOWNLOAD


@dataclass
class BatchRun:
    """Batch-wide context (was: _do_run_batch locals before the img loop)."""
    bridge: Any
    ctrl: Any
    urls: List[Any]
    allowed: List[str]
    primary_tab_id: str
    prompt_template: str
    suffix: str
    overwrite: bool
    preserve_format: bool
    unique_tpl: str
    gen_timeout: int
    highlight_duration: int
    action_stack: List[Any]
    selected_images: List[Any] = field(default_factory=list)


async def run_batch(bridge: Any) -> None:
    """Run batch using action blocks stack with visual confirmations."""
    try:
        run = await _prepare_run(bridge)
        if run is None:
            return
        if await _maybe_dispatch_parallel(run):
            return
        if not await _batch_start_gate(run):
            return
        for img in run.selected_images:
            if await _run_image(run, img) is BREAK:
                break
        b = run.bridge
        if b._cancel_requested:
            b._log("🏁 Batch cancelled by user", "warn")
        else:
            b._log("🏁 Batch complete", "success")
        b._run_state = "idle"
        b._emit_arena_state()
    except asyncio.CancelledError:
        _handle_batch_cancelled(run)
        raise
    except Exception as e:
        _handle_batch_crash(bridge, e)


def _handle_batch_cancelled(run: BatchRun) -> None:
    b = run.bridge
    b._log("🏁 Batch cancelled", "warn")
    b._run_state = "idle"
    try:
        b._settle_stuck_primary(run.primary_tab_id)
    except Exception:
        pass
    b._emit_arena_state()


def _handle_batch_crash(bridge: Any, e: Exception) -> None:
    if "Cancelled" in str(e) or bridge._cancel_requested:
        bridge._log(f"🏁 Batch cancelled: {e}", "warn")
    else:
        bridge._log(f"Batch runner crashed: {e}", "error")
    import traceback
    traceback.print_exc()
    bridge._run_state = "idle"
    bridge._emit_arena_state()


async def _prepare_run(bridge: Any) -> Optional[BatchRun]:
    """Batch setup: ctrl, urls/tabs, readiness, settings, action stack."""
    ctrl = CDPArenaController(bridge.cdp, log_callback=lambda m: bridge._log(m, "info"))
    urls = bridge._get_enabled_urls()
    allowed = enabled_tab_ids(urls)
    primary_tab_id = await bridge._select_run_tab(getattr(bridge.cdp, "_current_tab_id", "") or "", allowed)
    if not primary_tab_id:
        bridge._log(f"❌ No usable checked tab in pool — check a URL row linked to a live tab — pool: {bridge._pool_summary()}", "error")
        return None
    ready, reasons = await ctrl.is_page_ready()
    if not ready:
        bridge._log(f"⚠ Page not ready: {', '.join(reasons)} — trying anyway", "warn")
    out = bridge.state.settings.output
    run = BatchRun(
        bridge=bridge, ctrl=ctrl, urls=urls, allowed=allowed,
        primary_tab_id=primary_tab_id,
        prompt_template=bridge.state.prompt.get("user_prompt", ""),
        suffix=out.get("suffix", "_AI"),
        overwrite=out.get("overwrite", False),
        preserve_format=out.get("preserve_format", True),
        unique_tpl=out.get("unique_suffix_template", "{base}_AI_{n}{ext}"),
        gen_timeout=bridge.state.settings.timeouts.get("generation", 180) * 1000,
        highlight_duration=bridge.config.get_state("highlight_duration", 3),
        action_stack=bridge._get_action_blocks(),
        selected_images=bridge._get_selected_images(),
    )
    bridge._emit_action_blocks()
    _log_stack_banner(bridge, run.action_stack)
    return run


def _log_stack_banner(bridge: Any, action_stack: list) -> None:
    bridge._log(f"📦 Action blocks stack: {len(action_stack)} blocks — " + ", ".join(
        f"{b.display_name}({'ON' if b.enabled else 'OFF'})" for b in action_stack[:6])
        + ("..." if len(action_stack) > 6 else ""), "info")


async def _maybe_dispatch_parallel(run: BatchRun) -> bool:
    """Multi-page parallel dispatch: only tabs owned by CHECKED rows count (I-33)."""
    b = run.bridge
    try:
        if b._page_pool and len(run.selected_images) >= 2:
            total, free = counts_in(b._page_pool, run.allowed)
            if total >= 2 and free >= 1:
                b._log(f"🚀 Parallel mode: {total} pages {free} free, {len(run.selected_images)} images — dispatching to different pages steady/busy tracked, no double-send", "success")
                b._emit_pool_status()
                from app.services.multi_page_dispatcher import dispatch_parallel
                await dispatch_parallel(b, b._page_pool, run.selected_images, run.urls)
                return True
            elif total == 1:
                b._log(f"ℹ Pool has only {total} page — connect 2nd tab via Page Pool → Add Selected Tab or URL LIST Connect for parallel. Running sequentially on 1 page.", "warn")
            elif total == 0:
                b._log("ℹ Pool empty — using primary CDP connection single mode. Connect tabs to enable parallel.", "info")
    except Exception as e:
        b._log(f"Parallel dispatch check failed {e}, fallback to single", "warn")
    return False


async def _batch_start_gate(run: BatchRun) -> bool:
    """Batch-start gate (single mode): wait out cooldown + ready (spec 02/03)."""
    b = run.bridge
    try:
        if b._page_pool and run.primary_tab_id:
            await b._ensure_pool_page(run.primary_tab_id)
            _batch_go = await wait_for_batch_ready(b._page_pool, [run.primary_tab_id], b)
            if not _batch_go:
                b._log("Batch start aborted during cooldown wait", "warn")
                b._run_state = "idle"
                b._emit_arena_state()
                return False
    except Exception as e:
        b._log(f"Batch-start cooldown wait skipped: {e}", "warn")
    return True


async def _run_image(run: BatchRun, img: Any) -> Optional[str]:
    """One image: prelude, claim, block loop, finish. BREAK stops the batch."""
    b = run.bridge
    sig = await _image_prelude(run)
    if sig is BREAK:
        return BREAK
    job = _claim_image(run, img)
    job_failed, job_error = await _run_blocks(run, job)
    job.job_failed, job.job_error = job_failed, job_error
    if b._cancel_requested:
        b._log(f"[{job.correlation_id}] ❌ Cancelled — aborting batch", "warn")
        img.status = ImageStatus.FAILED.value
        img.error = "Cancelled by user"
        b.state.recalculate_progress()
        b._save_arena()
        return BREAK
    if _finish_image(run, job) is BREAK:
        return BREAK
    return await _post_image(run, job)


async def _await_pause(run: BatchRun) -> None:
    """Hold the batch while the user requested a pause."""
    b = run.bridge
    while getattr(b, "_pause_requested", False):
        b._log("Paused, waiting for resume...", "warn")
        await asyncio.sleep(1)
        if b._cancel_requested:
            break


async def _image_prelude(run: BatchRun) -> Optional[str]:
    """Cancel/stop-after/pause gates, tab reselect, per-tab cooldown gate."""
    b = run.bridge
    if b._cancel_requested:
        b._log("Batch cancelled", "warn")
        return BREAK
    if getattr(b, "_stop_after", False):
        b._log("Stopping after current as requested", "warn")
        return BREAK
    await _await_pause(run)
    if b._cancel_requested:
        b._log("Batch cancelled after pause", "warn")
        return BREAK
    # Prefer a ready CHECKED tab per image (primary may have cooled); then gate.
    run.primary_tab_id = await b._select_run_tab(run.primary_tab_id, run.allowed)
    if not run.primary_tab_id:
        b._log("❌ No usable checked tab left in pool — stopping batch", "error")
        return BREAK
    try:
        from app.services.cooldown_service import wait_for_tab_ready
        if b._page_pool and run.primary_tab_id:
            await b._ensure_pool_page(run.primary_tab_id)
            _tab_ready = await wait_for_tab_ready(b._page_pool, run.primary_tab_id, b)
            if not _tab_ready and b._cancel_requested:
                return BREAK
    except Exception as _e:
        b._log(f"Cooldown gate skipped: {_e}", "warn")
    return None


def _claim_image(run: BatchRun, img: Any) -> JobState:
    """Record the tab's OWN checked row, mark processing, mint the job id."""
    b = run.bridge
    url_row = pick_url_for_tab(run.urls, run.primary_tab_id)
    img.assigned_url_id = url_row.id if url_row else None
    img.attempt_count += 1
    img.status = ImageStatus.PROCESSING.value
    b.state.recalculate_progress()
    b._save_arena()
    b._start_tab_image(run.primary_tab_id, img)
    correlation_id = generate_correlation_id()
    job = JobState(img=img, correlation_id=correlation_id, job_id=correlation_id,
                   final_prompt=build_final_prompt(correlation_id, run.prompt_template))
    b._log(f"[{correlation_id}] Starting {img.relative_path} with URL {url_row.url if url_row else 'N/A'}", "info")
    try:
        b.job_started.emit(job.job_id, img.absolute_path)
    except Exception:
        pass
    return job


async def _block_precheck(run: BatchRun, job: JobState, block: Any) -> Optional[str]:
    """Stop/disabled/pre-delay gates before a block runs."""
    b = run.bridge
    if b._run_stop_requested(run.primary_tab_id):
        b._log(f"[{job.correlation_id}] ❌ Cancelled before block {block.display_name}", "warn")
        job.job_failed = True
        job.job_error = b._stop_reason(run.primary_tab_id)
        return BREAK
    if not block.enabled:
        b._emit_job_action_status(job.job_id, block, "skipped", f"Skipped (disabled)")
        return CONTINUE
    if block.pre_delay_ms and block.pre_delay_ms > 0:
        await asyncio.sleep(block.pre_delay_ms / 1000.0)
        if b._run_stop_requested(run.primary_tab_id):
            b._log(f"[{job.correlation_id}] ❌ Cancelled during pre-delay {block.display_name}", "warn")
            job.job_failed = True
            job.job_error = b._stop_reason(run.primary_tab_id)
            return BREAK
    return None


async def _run_blocks(run: BatchRun, job: JobState) -> tuple:
    """The block loop: pre-checks, dispatch, per-block error handling."""
    b = run.bridge
    for block in run.action_stack:
        pre = await _block_precheck(run, job, block)
        if pre is BREAK:
            break
        if pre is CONTINUE:
            continue
        btype = block.block_id
        b._emit_job_action_status(job.job_id, block, "running", f"Running {block.display_name}")
        b._log(f"[{job.correlation_id}] ▶ Block {block.display_name} ({btype}) running", "info")
        try:
            await _dispatch_block(run, job, block, btype)
        except Exception as e:
            job.job_failed = True
            job.job_error = str(e)
            b._log(f"[{job.correlation_id}] ❌ Block {block.display_name} failed: {e}", "error")
            b._emit_job_action_status(job.job_id, block, "failed", f"{e}")
            if getattr(block, "required", False):
                b._log(f"[{job.correlation_id}] Required block {btype} failed, aborting job", "error")
                break
            b._log(f"[{job.correlation_id}] Non-required block {btype} failed, continuing", "warn")
            continue
    return job.job_failed, job.job_error


def _finish_image(run: BatchRun, job: JobState) -> Optional[str]:
    """Mark the image failed/completed and emit job_finished."""
    b = run.bridge
    img = job.img
    if job.job_failed:
        img.status = ImageStatus.FAILED.value
        img.error = job.job_error
        b._log(f"[{job.correlation_id}] ❌ Failed {img.relative_path}: {job.job_error}", "error")
        if "Cancelled" in job.job_error:
            b.state.recalculate_progress()
            b._save_arena()
            return BREAK  # stop the whole image loop
        try:
            b.job_finished.emit(job.job_id, json.dumps({"status": "failed", "message": job.job_error, "output_path": img.output_path or ""}, ensure_ascii=False))
        except Exception:
            pass
        return None
    if img.status != ImageStatus.COMPLETED.value:
        img.status = ImageStatus.COMPLETED.value
    b._log(f"[{job.correlation_id}] ✅ Job completed {img.relative_path}", "success")
    try:
        b.job_finished.emit(job.job_id, json.dumps({"status": "completed", "message": f"Saved to {img.output_path}", "output_path": img.output_path or ""}, ensure_ascii=False))
    except Exception:
        pass
    return None


async def _post_image(run: BatchRun, job: JobState) -> Optional[str]:
    """Recalc+save, rate-limit note, post-generation reset, cancel gate."""
    b = run.bridge
    b.state.recalculate_progress()
    b._save_arena()
    # Rate-limit failure: stack the longer back-off before the base cooldown
    if job.job_failed and job.job_error:
        from app.services.cooldown_service import maybe_note_rate_limit
        maybe_note_rate_limit(b._page_pool, run.primary_tab_id, b, job.job_error)
    # Post-generation reset + cooldown (single-page)
    await b._finish_primary_tab(run.ctrl, run.primary_tab_id)
    if b._cancel_requested:
        return BREAK
    await asyncio.sleep(1)
    return None


async def _dispatch_block(run: BatchRun, job: JobState, block: Any, btype: str) -> None:
    """Dispatch one block to its handler (was: the elif ladder)."""
    handler = _BLOCK_HANDLERS.get(btype)
    if handler is None:
        b = run.bridge
        b._log(f"[{job.correlation_id}] Unknown block type {btype}, skipping", "warn")
        b._emit_job_action_status(job.job_id, block, "skipped", f"Unknown type {btype}")
        return
    await handler(run, job, block)


def _cf_request(block: Any) -> ClickRequest:
    """ClickRequest from CUSTOM_FIND block fields (Old App pattern)."""
    return ClickRequest(
        selector=block.selector or "button",
        label_selector=block.label_selector or "",
        match_text=block.match_text or "",
        match_mode=block.match_mode or "contains",
        click_enabled=block.click_enabled,
        click_selector=block.click_selector or "",
        highlight_enabled=block.highlight_enabled,
        confirm_pause_ms=block.confirm_pause_ms or 700,
        highlight_ms=block.highlight_ms or block.highlight_duration_ms or 2000,
        label=block.display_name or block.name,
    )


async def _block_custom_find(run: BatchRun, job: JobState, block: Any) -> None:
    """Generic CUSTOM_FIND — click on btn/text areas with visual confirmations."""
    b, ctrl = run.bridge, run.ctrl
    result = await find_and_click(b.cdp, _cf_request(block), engine=b)
    if result == "ok":
        # Try to get last rect from stash highlight — we already emitted via engine.report
        # For UI, also highlight selector for confirmation
        await _emit_success_with_rect(run, job, block, {
            "msg": f"FIND+CLICK ok {block.selector}", "sel": block.selector,
            "color": block.color, "duration": block.highlight_ms,
            "caption": block.display_name})
    else:
        await _cf_fallbacks(run, job, block)


def _fallback_request(block: Any, fb_sel: str, label: str) -> ClickRequest:
    """ClickRequest for a fallback selector (no label selector, forced click)."""
    return ClickRequest(
        selector=fb_sel,
        label_selector="",
        match_text=block.fallback_text or "",
        match_mode="contains",
        click_enabled=True,
        click_selector="",
        highlight_enabled=block.highlight_enabled,
        confirm_pause_ms=block.confirm_pause_ms,
        highlight_ms=block.highlight_ms,
        label=label,
    )


async def _cf_fallbacks(run: BatchRun, job: JobState, block: Any) -> None:
    """CUSTOM_FIND fallback list (comma-separated selectors)."""
    b = run.bridge
    fallback_list = []
    if block.fallback_selector:
        fallback_list = [s.strip() for s in block.fallback_selector.split(',') if s.strip()]
    success_fb = None
    for fb_sel in fallback_list:
        b._log(f"[{job.correlation_id}] ↩ Trying fallback {fb_sel} for {block.display_name}", "warn")
        fallback_req = _fallback_request(block, fb_sel, f"{block.display_name} fallback {fb_sel[:30]}")
        result2 = await find_and_click(b.cdp, fallback_req, engine=b)
        if result2 == "ok":
            success_fb = fb_sel
            break
    if success_fb:
        b._emit_job_action_status(job.job_id, block, "success", f"Fallback ok {success_fb}")
    elif fallback_list:
        raise RuntimeError(f"Find & Click failed for {block.selector} and fallbacks {fallback_list}")
    else:
        raise RuntimeError(f"Find & Click failed for {block.selector}")


def _hl_spec(block: Any) -> HighlightSpec:
    """HighlightSpec for a highlight-only block (visual confirmation)."""
    return HighlightSpec(
        label_selector=block.label_selector or None,
        match_text=block.match_text or None,
        match_mode=block.match_mode or "contains",
        color=block.color or "#00c853",
        caption=block.display_name or block.selector[:30],
        highlight_ms=block.highlight_ms or block.highlight_duration_ms or 2000,
        clear_first=True,
    )


def _hl_report(run: BatchRun, job: JobState, block: Any, res: dict) -> None:
    """Log + emit the highlight probe outcome; raises when not found."""
    b = run.bridge
    rect = res.get("rect")
    msg = f"Highlighted {block.selector} at {rect}" if rect else f"Highlight attempted {block.selector}"
    level = "success" if res.get("found") else "warn"
    b._log(f"[{job.correlation_id}] {msg}", level)
    b._emit_job_action_status(job.job_id, block, "success" if res.get("found") else "failed", msg, rect=rect)
    if not res.get("found"):
        raise RuntimeError(f"Highlight not found: {block.selector}")


async def _block_highlight(run: BatchRun, job: JobState, block: Any) -> None:
    """Pure visual confirmation — no click, no stash touch."""
    b = run.bridge
    try:
        # Build JS probe directly for highlight-only
        from app.browser.dom_highlight import build_highlight_probe
        js = build_highlight_probe(block.selector or "div", _hl_spec(block))
        raw = await b.cdp.evaluate(js)
        import json as _js
        _hl_report(run, job, block, _js.loads(raw) if raw else {})
    except Exception as e:
        raise RuntimeError(f"Highlight failed: {e}")


async def _block_pause(run: BatchRun, job: JobState, block: Any) -> None:
    """PAUSE: sleep extra.duration_ms / timeout_ms (default 1s)."""
    b = run.bridge
    dur = getattr(block, 'extra', {}).get('duration_ms') or getattr(block, 'timeout_ms', 1000) or 1000
    # extra may hold duration_ms
    if isinstance(block.extra, dict) and "duration_ms" in block.extra:
        dur = block.extra["duration_ms"]
    b._log(f"[{job.correlation_id}] ⏸ Pausing {dur}ms", "info")
    await asyncio.sleep(dur / 1000.0)
    b._emit_job_action_status(job.job_id, block, "success", f"Paused {dur}ms")


async def _block_type_prompt(run: BatchRun, job: JobState, block: Any) -> None:
    """TYPE_PROMPT — type with speed (Arena version of TYPE_MESSAGE)."""
    b, ctrl = run.bridge, run.ctrl
    typing_speed = 10
    if isinstance(block.extra, dict):
        typing_speed = block.extra.get("typing_speed_ms", 10)
    prompt_to_type = job.final_prompt
    b._log(f"[{job.correlation_id}] ⌨ Typing prompt {len(prompt_to_type)} chars speed {typing_speed}ms", "info")
    # Highlight first
    if block.highlight_enabled:
        try:
            await ctrl.highlight_selector(block.selector or textarea_primary(), color=block.color, duration_ms=block.highlight_ms, caption=block.display_name)
        except Exception:
            pass
    ok, reason = await ctrl.insert_prompt(prompt_to_type)
    if not ok:
        raise RuntimeError(f"Type prompt failed: {reason}")
    b._emit_job_action_status(job.job_id, block, "success", reason)


async def _block_baseline(run: BatchRun, job: JobState, block: Any) -> None:
    """OBSERVE_BASELINE: capture outputs, remember original srcs."""
    b = run.bridge
    job.baseline = await run.ctrl.capture_baseline()
    try:
        job.original_old_srcs = list(job.baseline.get("output_srcs", []) or [])
        job.original_old_outputs = list(job.baseline.get("outputs", []) or [])
    except Exception:
        job.original_old_srcs = []
        job.original_old_outputs = []
    b._log(f"[{job.correlation_id}] Baseline: {job.baseline.get('output_count')} existing outputs, original_old_srcs={len(job.original_old_srcs)} original_old_outputs={len(job.original_old_outputs)}", "info")
    b._emit_job_action_status(job.job_id, block, "success", f"Baseline {job.baseline.get('output_count')} outputs")


async def _block_check_security(run: BatchRun, job: JobState, block: Any) -> None:
    """CHECK_SECURITY: solve or wait; overlay+pause handled by choke point."""
    b, ctrl = run.bridge, run.ctrl
    if await ctrl.is_security_dialog_visible():
        b._emit_job_action_status(job.job_id, block, "running", "Security dialog visible — solving or waiting")
        b._run_state = "paused"
        b._pause_requested = True
        b._emit_arena_state()
        try:
            await b._settle_captcha_at(ctrl, run.primary_tab_id, job.correlation_id, "check-security")
        finally:
            b._pause_requested = False
            b._run_state = "running"
            b._emit_arena_state()
        b._emit_job_action_status(job.job_id, block, "success", "Security dialog solved")
    else:
        b._emit_job_action_status(job.job_id, block, "success", "No security dialog")


async def _block_highlight_family(run: BatchRun, job: JobState, block: Any) -> None:
    """HIGHLIGHT_ATTACH / HIGHLIGHT_PROMPT / HIGHLIGHT_SUBMIT."""
    b = run.bridge
    btype = block.block_id
    try:
        sel = block.selector or ('input[type="file"]' if "ATTACH" in btype else textarea_primary() if "PROMPT" in btype else send_presence_selector())
        await _emit_success_with_rect(run, job, block, {
            "msg": f"Highlighted {sel}", "sel": sel,
            "caption": block.display_name, "optional": True})
    except Exception as e:
        b._emit_job_action_status(job.job_id, block, "success", f"Highlight skipped: {e}")


async def _emit_success_with_rect(run: BatchRun, job: JobState, block: Any, opts: dict) -> None:
    """Highlight opts['sel'], then emit success with the rect.

    Plain success on failure unless opts['optional']; opts keys:
    msg, sel, color, duration, caption, optional."""
    b = run.bridge
    duration = opts.get("duration")
    if duration is None:
        duration = block.highlight_ms or block.highlight_duration_ms
    try:
        rect = await run.ctrl.highlight_selector(opts["sel"], color=opts.get("color") or block.color, duration_ms=duration, caption=opts.get("caption") or block.display_name)
        rd = rect if isinstance(rect, dict) else None
        if isinstance(rect, dict) and rect.get("rect"):
            rd = rect.get("rect")
        b._emit_job_action_status(job.job_id, block, "success", opts["msg"], rect=rd)
    except Exception:
        if opts.get("optional"):
            raise
        b._emit_job_action_status(job.job_id, block, "success", opts["msg"])


async def _block_attach(run: BatchRun, job: JobState, block: Any) -> None:
    """ATTACH_IMAGE: optional human-like dialog click, then CDP attach."""
    b, ctrl = run.bridge, run.ctrl
    img = job.img
    b._log(f"[{job.correlation_id}] Attaching {img.absolute_path}", "info")
    # If block has click_selector (human-like open dialog), use visual click first
    if block.click_selector and block.click_enabled:
        try:
            req = ClickRequest(
                selector=block.click_selector,
                label_selector="",
                match_text="",
                click_enabled=True,
                click_selector="",
                highlight_enabled=block.highlight_enabled,
                confirm_pause_ms=block.confirm_pause_ms,
                highlight_ms=block.highlight_ms,
                label=f"{block.display_name} open dialog",
            )
            await find_and_click(b.cdp, req, engine=b)
            await asyncio.sleep(0.5)
        except Exception as e:
            b._log(f"[{job.correlation_id}] Open dialog click skipped: {e}", "warn")
    ok, reason = await ctrl.attach_image(img.absolute_path)
    if not ok:
        raise RuntimeError(f"Attach failed: {reason}")
    b._log(f"[{job.correlation_id}] Attachment verified: {reason}", "success")
    await _emit_success_with_rect(run, job, block, {
        "msg": f"{reason}", "sel": block.selector or 'input[type="file"]',
        "caption": f"Attached {img.filename}"})


async def _block_verify_attachment(run: BatchRun, job: JobState, block: Any) -> None:
    """VERIFY_ATTACHMENT: check preview exists via find probe."""
    b = run.bridge
    sel = block.selector or "div.flex.flex-wrap.gap-2 img"
    try:
        from app.browser.dom_highlight import build_find_probe
        from app.browser.probe_requests import FindProbeSpec
        js = build_find_probe(sel, FindProbeSpec(highlight=block.highlight_enabled, highlight_ms=block.highlight_ms or 1500, color=block.color))
        raw = await b.cdp.evaluate(js)
        import json as _j
        res = _j.loads(raw) if raw else {}
        if res.get("found"):
            b._emit_job_action_status(job.job_id, block, "success", f"Attachment preview found {sel}", rect=res.get("rect"))
        else:
            raise RuntimeError(f"Attachment preview not found: {sel}")
    except Exception as e:
        raise RuntimeError(f"Verify attachment failed: {e}")


async def _block_insert_prompt(run: BatchRun, job: JobState, block: Any) -> None:
    """INSERT_PROMPT with the job correlation token."""
    b, ctrl = run.bridge, run.ctrl
    b._log(f"[{job.correlation_id}] Inserting prompt with token [{job.correlation_id}]", "info")
    if block.highlight_enabled:
        try:
            await ctrl.highlight_selector(block.selector or textarea_primary(), color=block.color, duration_ms=block.highlight_ms or 1000, caption=block.display_name)
        except Exception:
            pass
    ok, reason = await ctrl.insert_prompt(job.final_prompt)
    if not ok:
        raise RuntimeError(f"Prompt insert failed: {reason}")
    b._emit_job_action_status(job.job_id, block, "success", f"{reason}")


async def _block_verify_prompt(run: BatchRun, job: JobState, block: Any) -> None:
    """VERIFY_PROMPT: verify, one re-insert, then fail hard."""
    b, ctrl = run.bridge, run.ctrl
    verified, vreason = await ctrl.verify_prompt(job.final_prompt)
    if not verified:
        b._log(f"[{job.correlation_id}] Prompt mismatch {vreason}, retrying", "warn")
        ok, reason = await ctrl.insert_prompt(job.final_prompt)
        verified, vreason = await ctrl.verify_prompt(job.final_prompt)
        if not verified:
            raise RuntimeError(f"Prompt verification failed: {vreason}")
    b._emit_job_action_status(job.job_id, block, "success", f"Verified {vreason}")


def _submit_request(block: Any) -> ClickRequest:
    """Primary submit ClickRequest (visual runner)."""
    return ClickRequest(
        selector=block.selector or send_click_primary(),
        label_selector=block.label_selector or "",
        match_text=block.match_text or "",
        match_mode=block.match_mode or "contains",
        click_enabled=block.click_enabled,
        click_selector=block.click_selector or "",
        highlight_enabled=block.highlight_enabled,
        confirm_pause_ms=block.confirm_pause_ms or 700,
        highlight_ms=block.highlight_ms or block.highlight_duration_ms or 2000,
        label=block.display_name,
    )


async def _block_submit(run: BatchRun, job: JobState, block: Any) -> None:
    """SUBMIT once via visual runner, fallback list, then controller."""
    b, ctrl = run.bridge, run.ctrl
    b._log(f"[{job.correlation_id}] Submitting once via {block.selector}", "info")
    # Wait a bit for React to enable button after prompt insertion (user log shows 0 nodes when disabled)
    try:
        await asyncio.sleep(0.8)
    except Exception:
        pass
    result = await find_and_click(b.cdp, _submit_request(block), engine=b)
    if result != "ok":
        await _submit_fallbacks(run, job, block, req)
    else:
        b._emit_job_action_status(job.job_id, block, "success", f"Clicked {block.selector}")
    await b._settle_boundary_captcha(ctrl, run.primary_tab_id, job.correlation_id, "submit")


async def _submit_fallbacks(run: BatchRun, job: JobState, block: Any, req: Any) -> None:
    """Submit fallback list, then the controller's improved selectors."""
    b, ctrl = run.bridge, run.ctrl
    fallback_list = []
    if block.fallback_selector:
        fallback_list = [s.strip() for s in block.fallback_selector.split(',') if s.strip()]
    success_fallback = None
    for fb_sel in fallback_list:
        b._log(f"[{job.correlation_id}] ↩ Submit fallback trying {fb_sel}", "warn")
        fb_req = _fallback_request(block, fb_sel, f"Submit fallback {fb_sel[:40]}")
        result2 = await find_and_click(b.cdp, fb_req, engine=b)
        if result2 == "ok":
            success_fallback = fb_sel
            break
    if success_fallback:
        b._emit_job_action_status(job.job_id, block, "success", f"Submit via fallback {success_fallback}")
    else:
        # Last resort: try ctrl.submit() which has improved selectors + wait for enabled
        b._log(f"[{job.correlation_id}] ↩ Submit via controller fallback (improved selectors)", "warn")
        ok, reason = await ctrl.submit()
        if not ok:
            raise RuntimeError(f"Submit failed: {reason} and all fallbacks failed (tried {fallback_list})")
        b._emit_job_action_status(job.job_id, block, "success", f"Submit via controller {reason}")


@dataclass
class DlCtx:
    """Download-family loop state."""
    block: Any
    dl_success: bool = False
    last_dl_err: str = ""
    dl_cycle: int = 0


@dataclass
class WaitCtx:
    """Wait-family loop state (was: WAIT_OUTPUT branch locals)."""
    block: Any
    is_await: bool
    label: str
    wait_timeout: int
    effective_gen_timeout_sec: int
    max_wait_cycles: int = 2
    wait_success: bool = False
    last_wait_error: str = ""
    wait_cycle: int = 0
    data: Optional[dict] = None


async def _reload_and_recapture(run: BatchRun, job: JobState, why: Optional[str] = None, extra_count: bool = False) -> None:
    """Reload + recapture baseline, preserving original_old_srcs (the
    copy-pasted web from the old loop, now ONE function). `why` is the
    site-specific log prefix before the reload; extra_count adds the
    new_count_after_reload key some sites logged."""
    b = run.bridge
    ok_r, r_msg = await run.ctrl.reload_page()
    if why:
        b._log(f"[{job.correlation_id}] {why}: {ok_r} {r_msg}", "warn")
    await asyncio.sleep(3)
    try:
        _new_baseline_tmp = await run.ctrl.capture_baseline()
        # Keep original_old_srcs for detection, but update count for logging
        _orig_srcs = job.original_old_srcs if job.original_old_srcs else _new_baseline_tmp.get("output_srcs", [])
        job.baseline = {
            "output_count": _new_baseline_tmp.get("output_count", 0),
            "output_srcs": _orig_srcs,
            "timestamp": _new_baseline_tmp.get("timestamp", 0),
        }
        if extra_count:
            job.baseline["new_count_after_reload"] = _new_baseline_tmp.get("output_count", 0)
        b._log(f"[{job.correlation_id}] Baseline after reload: {job.baseline.get('output_count')} outputs (preserving original {len(_orig_srcs)} old srcs for new detection)", "info")
    except Exception as _e:
        b._log(f"[{job.correlation_id}] Baseline after reload failed: {_e}, keeping original", "warn")


async def _block_wait(run: BatchRun, job: JobState, block: Any) -> None:
    """WAIT_OUTPUT / AWAIT_PROCESSING_IMAGE: overlay + cycle loop + green rect."""
    b = run.bridge
    ctx = await _wait_setup(run, job, block)
    job.wait_timeout = ctx.wait_timeout
    await _wait_cycles(run, job, block, ctx)
    # ── Clear watcher overlay after waiting (generation done or timeout) ──
    if ctx.wait_success:
        await _wait_teardown_success(run, job, ctx)
    else:
        # Even on failure, clear overlay to avoid stuck rect
        try:
            await run.ctrl.hide_watcher_overlay()
        except Exception:
            pass


def _effective_gen_timeout(b: Any, wait_timeout: int) -> int:
    """User watcher setting, widened to the block timeout when larger."""
    try:
        gen_timeout_sec = int(b.config.get_state("watcher_generation_timeout_sec", 600))
    except Exception:
        gen_timeout_sec = 600
    return max(gen_timeout_sec, int(wait_timeout / 1000)) if wait_timeout else gen_timeout_sec


async def _wait_setup(run: BatchRun, job: JobState, block: Any) -> WaitCtx:
    """Wait preamble: labels, timeout, watcher overlay, await highlight."""
    b, ctrl = run.bridge, run.ctrl
    is_await = block.block_id == "AWAIT_PROCESSING_IMAGE"
    label = "Waiting for image to finish generating" if is_await else "Waiting for generation"
    wait_timeout = block.timeout_ms or run.gen_timeout
    b._log(f"[{job.correlation_id}] {label} (timeout {wait_timeout}ms) — detects processing spinner, shows waiting state, reload after timeout", "info")
    b._emit_job_action_status(job.job_id, block, "waiting" if is_await else "running", f"{label} — watching for processing → new output, timeout {wait_timeout}ms, reload after 1st timeout")
    # ── Show watcher overlay on webpage left center — visual confirmation for user ──
    effective_gen_timeout_sec = _effective_gen_timeout(b, wait_timeout)
    try:
        await ctrl.show_watcher_overlay("wait for finish generation", kind="generation", timeout_sec=effective_gen_timeout_sec)
        b._log(f"[{job.correlation_id}] ⏳ Drawn watcher overlay: 'wait for finish generation' on left center page — sleep circle running, timeout {effective_gen_timeout_sec}s (user setting from win)", "info")
    except Exception as e:
        b._log(f"[{job.correlation_id}] Overlay show failed: {e}", "warn")
    if is_await:
        try:
            proc_sel = block.selector or "div:has-text(\"Processing\"), div:has-text(\"Generating\"), [data-state=\"loading\"], .spinner, [aria-busy=\"true\"]"
            await ctrl.highlight_selector(proc_sel, color="#FFAA00", duration_ms=block.highlight_ms or 2000, caption="Awaiting — processing detected")
            b._log(f"[{job.correlation_id}] Awaiting processing indicator {proc_sel} — will wait until gone", "info")
        except Exception:
            pass
    return WaitCtx(block=block, is_await=is_await, label=label, wait_timeout=wait_timeout,
                   effective_gen_timeout_sec=effective_gen_timeout_sec)


async def _wait_teardown_success(run: BatchRun, job: JobState, ctx: WaitCtx) -> None:
    """Overlay clear + GREEN rect + final wait status emit."""
    b, ctrl = run.bridge, run.ctrl
    block = ctx.block
    try:
        await ctrl.hide_watcher_overlay()
        b._log(f"[{job.correlation_id}] ✅ Generation overlay cleared — finished, showing new output confirmation", "success")
    except Exception:
        pass
    # GREEN rect for new output / waiting done
    try:
        await _emit_success_with_rect(run, job, block, _wait_done_opts(ctx, job))
    except Exception:
        b._emit_job_action_status(job.job_id, block, "success", f"New output {job.new_src[:60]}..." if job.new_src else f"{ctx.label} done")


def _wait_done_opts(ctx: WaitCtx, job: JobState) -> dict:
    """Green-rect emit options for a finished wait."""
    return {
        "msg": f"New output {job.new_src[:60]}... downloaded {len(job.file_bytes) if job.file_bytes else 0} bytes" if job.new_src else f"{ctx.label} done",
        "sel": ctx.block.selector or 'div.no-scrollbar img',
        "color": ctx.block.color or "#00c853",
        "duration": ctx.block.highlight_ms or 3000,
        "caption": "New output" if not ctx.is_await else "Processing finished — new output",
    }


async def _wait_after_result(run: BatchRun, job: JobState, ctx: WaitCtx, status: str) -> Optional[str]:
    """Stop/cancel gates right after wait_for_new_output returns."""
    b = run.bridge
    if b._run_stop_requested(run.primary_tab_id):
        b._log(f"[{job.correlation_id}] ❌ Cancelled after wait_for_new_output", "warn")
        job.job_failed = True
        job.job_error = b._stop_reason(run.primary_tab_id)
        return BREAK
    if ctx.data.get("cancelled") or (ctx.data.get("error") and "Cancelled" in str(ctx.data.get("error"))):
        b._log(f"[{job.correlation_id}] ❌ Cancelled (wait returned cancelled)", "warn")
        job.job_failed = True
        job.job_error = b._stop_reason(run.primary_tab_id)
        return BREAK
    return None


async def _wait_cycle_head(run: BatchRun, job: JobState, ctx: WaitCtx) -> Optional[str]:
    """Per-cycle prelude: stop gate, captcha check, after-retry notice."""
    b, ctrl = run.bridge, run.ctrl
    block = ctx.block
    wait_cycle = ctx.wait_cycle
    if b._run_stop_requested(run.primary_tab_id):
        b._log(f"[{job.correlation_id}] ❌ Cancelled during wait cycle {wait_cycle+1}", "warn")
        job.job_failed = True
        job.job_error = b._stop_reason(run.primary_tab_id)
        return BREAK
    # ── During generation wait, check for captcha — auto-solve or manual wait ──
    try:
        if await ctrl.is_security_dialog_visible():
            b._log(f"[{job.correlation_id}] ⚠ Captcha detected during generation wait — solving or waiting", "error")
            b._emit_job_action_status(job.job_id, block, "waiting", "Captcha during generation — solving or waiting")
            await b._settle_captcha_at(ctrl, run.primary_tab_id, job.correlation_id, "gen-wait")
            b._log(f"[{job.correlation_id}] ✅ Captcha solved during generation — restoring generation overlay", "success")
            try:
                await ctrl.show_watcher_overlay("wait for finish generation", kind="generation", timeout_sec=ctx.effective_gen_timeout_sec)
            except Exception:
                pass
    except Exception as e_cap:
        b._log(f"[{job.correlation_id}] Captcha check during generation failed: {e_cap}", "warn")
    if wait_cycle > 0:
        b._log(f"[{job.correlation_id}] 🔄 Wait cycle {wait_cycle+1}/{ctx.max_wait_cycles} after reload — waiting again {ctx.wait_timeout}ms", "warn")
        b._emit_job_action_status(job.job_id, block, "waiting", f"{ctx.label} retry {wait_cycle+1}/{ctx.max_wait_cycles} after reload, timeout {ctx.wait_timeout}ms")
    return None


def _wait_last_cycle_failed(run: BatchRun, job: JobState, ctx: WaitCtx) -> None:
    """Last wait cycle failed: non-required await continues, else hard fail."""
    b = run.bridge
    block = ctx.block
    if ctx.is_await and not block.required:
        b._log(f"[{job.correlation_id}] {ctx.label} timeout after {ctx.max_wait_cycles} cycles but non-required, continuing", "warn")
        b._emit_job_action_status(job.job_id, block, "success", f"Wait timeout after reload, continuing: {ctx.last_wait_error}")
        ctx.wait_success = True
        return
    raise RuntimeError(f"Generation timeout after {ctx.max_wait_cycles} cycles (each {ctx.wait_timeout}ms) incl reload retry: {ctx.last_wait_error}")


async def _wait_cycles(run: BatchRun, job: JobState, block: Any, ctx: WaitCtx) -> None:
    """The wait-cycle loop: original + after reload (max 2 cycles)."""
    for ctx.wait_cycle in range(ctx.max_wait_cycles):
        if await _wait_cycle_head(run, job, ctx) is BREAK:
            break
        status, ctx.data = await run.ctrl.wait_for_new_output(job.baseline, timeout_ms=ctx.wait_timeout, correlation_id=job.correlation_id, cancel_check=lambda: run.bridge._run_stop_requested(run.primary_tab_id))
        if await _wait_after_result(run, job, ctx, status) is BREAK:
            break
        sig = await _wait_completed(run, job, ctx) if status == "completed" else await _wait_failed(run, job, ctx)
        if sig is BREAK:
            break
        if sig is CONTINUE:
            continue
        # tail of each cycle (original 3363-3371): a plain fall-through lands here
        if ctx.wait_success:
            break
        if ctx.wait_cycle == ctx.max_wait_cycles - 1:
            _wait_last_cycle_failed(run, job, ctx)
            break
    # end for wait_cycle


def _log_order_check(run: BatchRun, job: JobState, ctx: WaitCtx, on_timeout: bool) -> None:
    """Log order verification details from the wait payload (debugging above)."""
    try:
        if not on_timeout:
            _order_log_completed(run, job, ctx)
        else:
            _order_log_timeout(run, job, ctx)
    except Exception:
        pass


def _order_log_completed(run, job, ctx) -> None:
    b, data = run.bridge, ctx.data
    order_check = data.get("orderCheck") or data.get("order_check") or ""
    if order_check or data.get("jobFound") is not None or data.get("allNew") is not None:
        b._log(f"[{job.correlation_id}] Order check: {order_check} jobFound={data.get('jobFound')} jobTop={data.get('jobTop')} prevTop={data.get('prevJobTop')} nextTop={data.get('nextJobTop')} validAbove={data.get('validAbove')} invalidAbove={data.get('invalidAbove')} allNew={data.get('allNew')} below={data.get('belowCount')} allJobs={data.get('allJobs')}", "info")
        if data.get("allNewDetails"):
            b._log(f"[{job.correlation_id}] allNewDetails: {data.get('allNewDetails')}", "info")
        if data.get("invalidAboveDetails"):
            b._log(f"[{job.correlation_id}] invalidAboveDetails: {data.get('invalidAboveDetails')}", "info")


def _order_log_timeout(run, job, ctx) -> None:
    b, data = run.bridge, ctx.data
    if data.get("orderCheck") or data.get("allNew") is not None:
        b._log(f"[{job.correlation_id}] Order check on timeout: {data.get('orderCheck')} validAbove={data.get('validAbove')} invalidAbove={data.get('invalidAbove')} allNew={data.get('allNew')} reason={ctx.last_wait_error} allJobs={data.get('allJobs')} jobTop={data.get('jobTop')} prevTop={data.get('prevJobTop')}", "info")
        if data.get("allNewDetails"):
            b._log(f"[{job.correlation_id}] allNewDetails timeout: {data.get('allNewDetails')}", "info")
        if data.get("invalidAboveDetails"):
            b._log(f"[{job.correlation_id}] invalidDetails timeout: {data.get('invalidAboveDetails')}", "info")
        if data.get("belowDetails"):
            b._log(f"[{job.correlation_id}] belowDetails timeout: {data.get('belowDetails')}", "info")


async def _wait_completed(run: BatchRun, job: JobState, ctx: WaitCtx) -> Optional[str]:
    """status == "completed": verification cascade, download test, reloads."""
    data = ctx.data
    _log_order_check(run, job, ctx, on_timeout=False)
    tmp_src = data.get("new_src")
    if tmp_src:
        return await _wait_verify_src(run, job, ctx, tmp_src)
    if ctx.block.block_id == "WAIT_OUTPUT":
        ctx.last_wait_error = "New output src not found after generation"
        if wait_cycle == 0:
            await _reload_and_recapture(run, job, extra_count=True)
            return CONTINUE
        return CONTINUE
    # AWAIT block can succeed without new_src
    ctx.wait_success = True
    run.bridge._log(f"[{job.correlation_id}] {ctx.label} done without new src (await block)", "info")
    return BREAK


async def _wait_jobid_mismatch(run: BatchRun, job: JobState, ctx: WaitCtx, ids) -> Optional[str]:
    """JOB-ID mismatch before download: wait when generating, reload once, then fail."""
    b, ctrl = run.bridge, run.ctrl
    expected, assoc = ids.expected, ids.assoc
    b._log(f"[{job.correlation_id}] ❌ JOB-ID mismatch before download: image associated {assoc} != expected {expected} (visualPrev {ids.visual_prev} domPrev {ids.dom_prev}) — NOT downloading incorrect image, will treat as error and continue waiting for correct", "error")
    ctx.last_wait_error = f"JOB-ID mismatch: expected {expected} but image belongs to {assoc}"
    is_gen, gen_details = await ctrl.is_generating()
    if is_gen:
        b._log(f"[{job.correlation_id}] Still generating {gen_details} after mismatch — continue waiting for correct {expected}", "warn")
        await asyncio.sleep(2)
        return CONTINUE
    if ctx.wait_cycle == 0:
        await _reload_and_recapture(run, job, why="Reload after JOB-ID mismatch")
        return CONTINUE
    b._log(f"[{job.correlation_id}] ❌ JOB-ID mismatch persists after reload — failing as error, not downloading wrong image", "error")
    raise RuntimeError(f"JOB-ID mismatch: expected {expected} but found {assoc} — not downloading incorrect image (after page reset bug)")


async def _wait_verify_src(run: BatchRun, job: JobState, ctx: WaitCtx, tmp_src: str) -> Optional[str]:
    """Strict JOB-ID verification before any download (page reset bug)."""
    b = run.bridge
    data = ctx.data
    ids = _wait_payload_ids(job, data)
    if ids.expected and ids.assoc and ids.assoc != ids.expected:
        sig = await _wait_jobid_mismatch(run, job, ctx, ids)
        if sig is not None:
            return sig
    sig = await _wait_job_not_found(run, job, ctx, ids.job_found)
    if sig is not None:
        return sig
    b._log(f"[{job.correlation_id}] ✅ Full verification passed before download: associated {ids.assoc} == expected {ids.expected} jobFound={ids.job_found} prompt above verified, will download after 3s", "success")
    return await _wait_download_test(run, job, ctx, tmp_src)


def _wait_payload_ids(job: JobState, data: dict):
    """Pull assoc/expected/jobFound ids from a wait payload (top or check)."""
    from types import SimpleNamespace
    check = data.get("check", {}) if isinstance(data.get("check", {}), dict) else {}
    return SimpleNamespace(
        assoc=data.get("associatedJobId") or check.get("associatedJobId"),
        expected=data.get("expectedJobId") or data.get("jobId") or job.correlation_id,
        visual_prev=data.get("visualPrevJobId") or check.get("visualPrevJobId"),
        dom_prev=data.get("domPrevJobId") or check.get("domPrevJobId"),
        job_found=data.get("jobFound") if "jobFound" in data else check.get("jobFound"),
    )


async def _wait_job_not_found(run: BatchRun, job: JobState, ctx: WaitCtx, job_found) -> Optional[str]:
    """Prompt not on the page anymore: reload once, then hard fail."""
    b, ctrl = run.bridge, run.ctrl
    if not (job.correlation_id and job_found is False):
        return None
    b._log(f"[{job.correlation_id}] ⚠️ Prompt with JOB-ID {job.correlation_id} not found on page before download — possible page reset cleared prompt, will not download old image, error", "error")
    ctx.last_wait_error = f"Prompt {job.correlation_id} not found on page (page reset?)"
    if ctx.wait_cycle == 0:
        ok_r, r_msg = await ctrl.reload_page()
        await asyncio.sleep(3)
        return CONTINUE
    raise RuntimeError(f"Prompt {job.correlation_id} not found on page after reset — not downloading")


async def _wait_download_test(run: BatchRun, job: JobState, ctx: WaitCtx, tmp_src: str) -> Optional[str]:
    """Download after 3s to verify it's actually downloadable; on failure
    check generation and reload-or-continue (the old web of retries)."""
    b, ctrl = run.bridge, run.ctrl
    block, wait_cycle = ctx.block, ctx.wait_cycle
    b._log(f"[{job.correlation_id}] ⏳ New src detected {tmp_src[:80]}... waiting 3s before verification download (user requested)", "info")
    await asyncio.sleep(3)
    try:
        s_test, f_test, c_test = await ctrl.download_image(tmp_src)
        if s_test and f_test and len(f_test) > 100:
            job.new_src = tmp_src
            job.file_bytes = f_test
            job.ctype = c_test
            b._log(f"[{job.correlation_id}] ✅ New output detected and verified downloadable: {tmp_src[:80]}... {len(f_test)} bytes", "success")
            ctx.wait_success = True
            return None
        return await _dt_not_ok(run, job, ctx, c_test)
    except Exception as e:
        b._log(f"[{job.correlation_id}] Download verification exception {e}, treating as not ready", "warn")
        is_gen, _ = await ctrl.is_generating()
        if is_gen:
            b._emit_job_action_status(job.job_id, block, "waiting", f"Exception but generating, continue waiting: {e}")
            await asyncio.sleep(2)
            return CONTINUE
        ctx.last_wait_error = str(e)
        if wait_cycle == 0:
            await _reload_and_recapture(run, job, why="Reload after download test failure", extra_count=True)
            return CONTINUE
        return CONTINUE


async def _dt_not_ok(run: BatchRun, job: JobState, ctx: WaitCtx, c_test: str) -> Optional[str]:
    """Download test failed: if still generating try again, else reload."""
    b, ctrl = run.bridge, run.ctrl
    block, wait_cycle = ctx.block, ctx.wait_cycle
    is_gen, gen_details = await ctrl.is_generating()
    if not is_gen:
        b._log(f"[{job.correlation_id}] Download test failed and not generating, will reload if first cycle", "warn")
        ctx.last_wait_error = f"Download test failed: {c_test}"
        if wait_cycle == 0:
            await _reload_and_recapture(run, job, why="Reload after download test failure", extra_count=True)
        return CONTINUE
    b._log(f"[{job.correlation_id}] ⏳ Download test failed but generation still in progress {gen_details} — returning to waiting state", "warn")
    b._emit_job_action_status(job.job_id, block, "waiting", f"Download not ready but generating {gen_details}, continue waiting")
    await asyncio.sleep(2)
    # Try wait again within same cycle (extend)
    status2, data2 = await ctrl.wait_for_new_output(job.baseline, timeout_ms=ctx.wait_timeout, correlation_id=job.correlation_id, cancel_check=lambda: b._run_stop_requested(run.primary_tab_id))
    if status2 == "completed" and data2.get("new_src"):
        job.new_src = data2.get("new_src")
        return await _dt_retry_download(run, job, ctx)
    ctx.last_wait_error = f"Wait failed after extra wait: {data2.get('error')}"
    if wait_cycle == 0:
        await _reload_and_recapture(run, job, why="Reload after download test failure", extra_count=True)
    return CONTINUE


async def _dt_retry_download(run: BatchRun, job: JobState, ctx: WaitCtx) -> Optional[str]:
    """Second download attempt inside the extended wait."""
    b, ctrl = run.bridge, run.ctrl
    wait_cycle = ctx.wait_cycle
    s2, f2, c2 = await ctrl.download_image(job.new_src)
    if s2 and f2 and len(f2) > 100:
        job.file_bytes = f2
        job.ctype = c2
        ctx.wait_success = True
        return None
    b._log(f"[{job.correlation_id}] Still not downloadable after extra wait, will try reload if first cycle", "warn")
    if wait_cycle == 0:
        await _reload_and_recapture(run, job, why="Reload after download test failure", extra_count=True)
        return CONTINUE
    ctx.last_wait_error = f"Download test failed after reload: {c2}"
    return CONTINUE


async def _wait_no_exact_above(run: BatchRun, job: JobState, ctx: WaitCtx) -> Optional[str]:
    """No exact above found: keep waiting when generating, reload once otherwise."""
    b, ctrl = run.bridge, run.ctrl
    block, wait_cycle = ctx.block, ctx.wait_cycle
    b._log(f"[{job.correlation_id}] ⏳ No exact above image for {job.correlation_id} — found invalid above (belongs to previous), awaiting next image above (if still generating)", "warn")
    b._emit_job_action_status(job.job_id, block, "waiting", f"No exact above, awaiting next above current prompt (prev belongs to previous)")
    is_gen, gen_details = await ctrl.is_generating()
    if is_gen:
        b._log(f"[{job.correlation_id}] Still generating {gen_details} — continue waiting for exact above", "info")
        await asyncio.sleep(2)
        return CONTINUE
    # Not generating but no exact above — maybe need reload? Try reload if first cycle
    if wait_cycle == 0:
        await _reload_and_recapture(run, job, why="Reload after no exact above (not generating)", extra_count=True)
    return CONTINUE


async def _wait_failed(run: BatchRun, job: JobState, ctx: WaitCtx) -> Optional[str]:
    """status != completed: timeout / no exact above found — reload dance."""
    b, ctrl = run.bridge, run.ctrl
    data = ctx.data
    ctx.last_wait_error = data.get("error") or data.get("reason") or "timeout"
    _log_order_check(run, job, ctx, on_timeout=True)
    # Special handling for exact above logic — if image above belongs to previous prompt, await next
    if ctx.last_wait_error in ("image_above_belongs_to_previous_prompt_await_next", "no_exact_above_found_wait_next", "no_exact_above_found_wait_next"):
        return await _wait_no_exact_above(run, job, ctx)
    is_gen, gen_details = await ctrl.is_generating()
    b._log(f"[{job.correlation_id}] ⏳ Wait timeout after {ctx.wait_timeout}ms cycle {ctx.wait_cycle+1}/{ctx.max_wait_cycles} — is_generating={is_gen} {gen_details}, error={ctx.last_wait_error}", "warn")
    if is_gen:
        b._log(f"[{job.correlation_id}] Generation still in progress after timeout, not failing yet — will reload if first cycle", "warn")
        b._emit_job_action_status(job.job_id, block, "waiting", f"Timeout but still generating {gen_details}, reload retry {ctx.wait_cycle+1}")
    if ctx.wait_cycle == 0:
        # First timeout: reload page, not fail yet (bad cache chance per user)
        b._log(f"[{job.correlation_id}] 🔄 Reloaded page after 2 min timeout (cycle {ctx.wait_cycle+1}): retrying wait", "warn")
        ok_r, r_msg = await ctrl.reload_page()
        await asyncio.sleep(3)
        try:
            baseline_after = await ctrl.capture_baseline()
            b._log(f"[{job.correlation_id}] Baseline after reload: {baseline_after.get('output_count')} outputs", "info")
        except Exception:
            pass
        return CONTINUE
    b._log(f"[{job.correlation_id}] Second wait timeout after reload — will fail now", "error")
    return CONTINUE


async def _block_download(run: BatchRun, job: JobState, block: Any) -> None:
    """DOWNLOAD: settle captcha, precheck, retry cycles with reloads."""
    b, ctrl = run.bridge, run.ctrl
    await b._settle_boundary_captcha(ctrl, run.primary_tab_id, job.correlation_id, "download")
    # DOWNLOAD should not fail until generation indicates finished and no jobs running
    if job.file_bytes and len(job.file_bytes) > 100:
        # Already downloaded during WAIT_OUTPUT verification — skip
        b._log(f"[{job.correlation_id}] Download already done during wait verification: {len(job.file_bytes)} bytes, skipping DOWNLOAD block", "info")
        b._emit_job_action_status(job.job_id, block, "success", f"Already downloaded {len(job.file_bytes)} bytes during wait")
        return
    if not job.new_src:
        raise RuntimeError("No new_src from previous wait block")
    await _dl_precheck(run, job)
    b._log(f"[{job.correlation_id}] ⏳ Waiting 3s before download as requested (not immediate) for stability: {job.new_src[:80]}...", "info")
    await asyncio.sleep(3)
    b._log(f"[{job.correlation_id}] Downloading highest-quality image after 3s delay: {job.new_src[:120]} (will return to waiting if generation in progress)", "info")
    b._emit_job_action_status(job.job_id, block, "running", f"Downloading after 3s delay {job.new_src[:60]}... — if fail and generating, return to waiting")
    dctx = DlCtx(block=block)
    await _dl_cycles(run, job, dctx)
    if dctx.dl_success:
        b._emit_job_action_status(job.job_id, block, "success", f"Downloaded {len(job.file_bytes)} bytes {job.ctype} (Python direct fallback for R2, with reload retry)")
    else:
        raise RuntimeError(f"Download failed after 2 cycles (each 5 attempts + reload + waiting check) — last error: {dctx.last_dl_err} src={job.new_src[:120]}. Only fails if page finished all tasks and no jobs running, with reload retry for bad cache.")


async def _dl_precheck(run: BatchRun, job: JobState) -> None:
    """Strict verification before DOWNLOAD (page reset bug)."""
    b = run.bridge
    try:
        gen_state = await run.ctrl.get_generation_state(job.correlation_id)
        chk = gen_state or {}
        assoc_dl = chk.get("associatedJobId") or chk.get("check", {}).get("associatedJobId") or chk.get("expectedJobId")
        expected_dl = job.correlation_id
        job_found_dl = chk.get("jobFound")
        if assoc_dl and expected_dl and assoc_dl != expected_dl:
            b._log(f"[{job.correlation_id}] ❌ JOB-ID mismatch in DOWNLOAD block: associated {assoc_dl} != expected {expected_dl} — NOT downloading, error", "error")
            raise RuntimeError(f"JOB-ID mismatch in DOWNLOAD: expected {expected_dl} but associated {assoc_dl} — not downloading incorrect image after reset")
        if job_found_dl is False:
            b._log(f"[{job.correlation_id}] ⚠️ Prompt {expected_dl} not found on page in DOWNLOAD check — possible reset, not downloading old image", "error")
            raise RuntimeError(f"Prompt {expected_dl} not found before download — page reset?")
        b._log(f"[{job.correlation_id}] ✅ DOWNLOAD pre-check passed: associated {assoc_dl} expected {expected_dl} jobFound={job_found_dl}", "success")
    except RuntimeError:
        raise
    except Exception as e:
        b._log(f"[{job.correlation_id}] DOWNLOAD pre-check exception {e} — continuing with caution (will verify during download attempts)", "warn")


async def _dl_cycles(run: BatchRun, job: JobState, dctx: DlCtx) -> None:
    """Download cycles: original + after reload (max 2), 5 attempts each."""
    b = run.bridge
    block = dctx.block
    max_dl_cycles = 2
    for dctx.dl_cycle in range(max_dl_cycles):
        if b._run_stop_requested(run.primary_tab_id):
            b._log(f"[{job.correlation_id}] ❌ Cancelled during download cycle {dctx.dl_cycle+1}", "warn")
            job.job_failed = True
            job.job_error = b._stop_reason(run.primary_tab_id)
            break
        if dctx.dl_cycle > 0:
            b._log(f"[{job.correlation_id}] 🔄 Download cycle {dctx.dl_cycle+1}/{max_dl_cycles} after reload", "warn")
            b._emit_job_action_status(job.job_id, block, "running", f"Download retry {dctx.dl_cycle+1}/{max_dl_cycles} after reload")
        dctx.dl_success = await _dl_attempts(run, job, dctx)
        if dctx.dl_success:
            break
        # After max_attempts in this cycle, check generation state
        await _dl_post_attempts(run, job, dctx)


async def _dl_wait_again(run: BatchRun, job: JobState, opts: dict) -> bool:
    """is_generating gate: wait for a fresh new_src and adopt it."""
    b, ctrl = run.bridge, run.ctrl
    is_gen, gen_details = await ctrl.is_generating()
    if not is_gen:
        return False
    b._log(f"[{job.correlation_id}] ⏳ {opts['why']} {gen_details} — returning to waiting state, will wait again", "warn")
    status_w, data_w = await ctrl.wait_for_new_output(job.baseline, timeout_ms=opts["timeout"], correlation_id=job.correlation_id, cancel_check=lambda: b._run_stop_requested(run.primary_tab_id))
    if status_w == "completed" and data_w.get("new_src"):
        job.new_src = data_w.get("new_src")
        b._log(f"[{job.correlation_id}] New output after waiting again: {job.new_src[:80]}", "info")
        return True
    if opts.get("note"):
        b._log(f"[{job.correlation_id}] {opts['note']}", "warn")
    return False


async def _dl_try_once(run: BatchRun, job: JobState, dctx: DlCtx, attempt: int) -> bool:
    """One download attempt; records last error. True when bytes arrived."""
    b = run.bridge
    s, f, c = await run.ctrl.download_image(job.new_src)
    if s and f and len(f) > 100:
        job.file_bytes = f
        job.ctype = c
        dctx.dl_success = True
        b._log(f"[{job.correlation_id}] ✅ Download attempt {attempt+1} succeeded: {len(f)} bytes {c}", "success")
        return True
    dctx.last_dl_err = c
    return False


async def _dl_attempts(run: BatchRun, job: JobState, dctx: DlCtx) -> bool:
    """Up to 5 download attempts per cycle; waits again when generating."""
    b, ctrl, block = run.bridge, run.ctrl, dctx.block
    max_attempts = 5
    for attempt in range(max_attempts):
        if b._run_stop_requested(run.primary_tab_id):
            b._log(f"[{job.correlation_id}] ❌ Cancelled during download attempt {attempt+1}", "warn")
            job.job_failed = True
            job.job_error = b._stop_reason(run.primary_tab_id)
            break
        try:
            if await _dl_try_once(run, job, dctx, attempt):
                break
            c = dctx.last_dl_err
            b._log(f"[{job.correlation_id}] Download attempt {attempt+1} failed: {c[:300]}", "warn")
            b._log(f"[{job.correlation_id}] Download attempt {attempt+1} failed: {c[:300]}", "warn")
            # Check if generation still in progress — if yes, return to waiting state
            if await _dl_wait_again(run, job, {
                    "why": "Download failed but generation still in progress",
                    "note": "Still no new output after waiting, continue download attempts",
                    "timeout": job.wait_timeout if job.wait_timeout is not None else run.gen_timeout}):
                continue
        except Exception as e:
            dctx.last_dl_err = str(e)
            b._log(f"[{job.correlation_id}] Download attempt {attempt+1} exception: {e}", "warn")
            if await _dl_wait_again(run, job, {"why": "Exception but generating",
                                               "timeout": run.gen_timeout}):
                continue
        await asyncio.sleep(1 + attempt)
    return dctx.dl_success


async def _dl_post_attempts(run: BatchRun, job: JobState, dctx: DlCtx) -> None:
    """After a failed cycle: wait again when generating, reload, or fail."""
    b, ctrl = run.bridge, run.ctrl
    block, dl_cycle = dctx.block, dctx.dl_cycle
    is_gen, gen_details = await ctrl.is_generating()
    b._log(f"[{job.correlation_id}] Download cycle {dl_cycle+1} failed after 5 attempts — is_generating={is_gen} {gen_details}", "warn")
    if is_gen:
        b._log(f"[{job.correlation_id}] Generation still in progress, not failing download yet — will wait again", "warn")
        b._emit_job_action_status(job.job_id, block, "waiting", f"Download failed but still generating {gen_details}, waiting again")
        status_w, data_w = await ctrl.wait_for_new_output(job.baseline, timeout_ms=run.gen_timeout, correlation_id=job.correlation_id, cancel_check=lambda: b._run_stop_requested(run.primary_tab_id))
        if status_w == "completed" and data_w.get("new_src"):
            job.new_src = data_w.get("new_src")
            b._log(f"[{job.correlation_id}] New src after waiting: {job.new_src[:80]} — retrying download", "info")
            if dl_cycle == 0:
                await _reload_and_recapture(run, job, why="Before download retry (generation)", extra_count=True)
            return
        if dl_cycle == 0:
            ok_r, r_msg = await ctrl.reload_page()
            b._log(f"[{job.correlation_id}] Reload after download failure while generating: {ok_r} {r_msg}", "warn")
            await asyncio.sleep(3)
            await _recapture_only(run, job)
        return
    await _dl_not_generating(run, job, dctx)


async def _recapture_only(run: BatchRun, job: JobState) -> None:
    """Recapture baseline after a reload (preserving original_old_srcs)."""
    b = run.bridge
    try:
        _new_baseline_tmp = await run.ctrl.capture_baseline()
        _orig_srcs = job.original_old_srcs if job.original_old_srcs else _new_baseline_tmp.get("output_srcs", [])
        job.baseline = {
            "output_count": _new_baseline_tmp.get("output_count", 0),
            "output_srcs": _orig_srcs,
            "timestamp": _new_baseline_tmp.get("timestamp", 0),
            "new_count_after_reload": _new_baseline_tmp.get("output_count", 0),
        }
        b._log(f"[{job.correlation_id}] Baseline after reload: {job.baseline.get('output_count')} outputs (preserving original {len(_orig_srcs)} old srcs for new detection)", "info")
    except Exception as _e:
        b._log(f"[{job.correlation_id}] Baseline after reload failed: {_e}, keeping original", "warn")


async def _dl_not_generating(run: BatchRun, job: JobState, dctx: DlCtx) -> None:
    """Not generating: reload once before the final fail (bad cache)."""
    b, ctrl = run.bridge, run.ctrl
    block, dl_cycle = dctx.block, dctx.dl_cycle
    if dl_cycle == 0:
        b._log(f"[{job.correlation_id}] Download failed and not generating (page finished tasks) — trying reload once before final fail (bad cache)", "warn")
        b._emit_job_action_status(job.job_id, block, "waiting", f"Not generating but download failed, reload retry {dl_cycle+1}")
        await _dl_reload_latest(run, job)
        return
    # Second cycle after reload also failed and not generating — now fail
    b._log(f"[{job.correlation_id}] Second download attempt after reload also failed and not generating — failing", "error")


def _pick_latest_new_src(run: BatchRun, job: JobState, latest_srcs: list) -> None:
    """Adopt the latest src not present in original_old_srcs, if any."""
    b = run.bridge
    if not latest_srcs:
        return
    _found_new = None
    for _src in reversed(latest_srcs):
        if _src not in job.original_old_srcs:
            _found_new = _src
            break
    if _found_new:
        if _found_new != job.new_src:
            job.new_src = _found_new
            b._log(f"[{job.correlation_id}] Using latest NEW src after reload (not in original): {job.new_src[:120]}", "info")
        else:
            b._log(f"[{job.correlation_id}] Retrying same src after reload (still new)", "info")
    else:
        b._log(f"[{job.correlation_id}] No new src in latest_baseline after reload (all old), keeping {job.new_src[:80] if job.new_src else 'None'}", "warn")


async def _dl_reload_latest(run: BatchRun, job: JobState) -> None:
    """Reload, then pick the latest NEW src not in original_old_srcs."""
    b, ctrl = run.bridge, run.ctrl
    ok_r, r_msg = await ctrl.reload_page()
    await asyncio.sleep(3)
    try:
        latest_baseline = await ctrl.capture_baseline()
        _pick_latest_new_src(run, job, latest_baseline.get("output_srcs", []))
        # Preserve original_old_srcs for next detection
        job.baseline = {
            "output_count": latest_baseline.get("output_count", 0),
            "output_srcs": job.original_old_srcs if job.original_old_srcs else latest_baseline.get("output_srcs", []),
            "timestamp": latest_baseline.get("timestamp", 0),
        }
    except Exception as e:
        b._log(f"[{job.correlation_id}] Baseline after reload failed: {e}", "warn")


def _fallback_ext(new_src: Optional[str]) -> str:
    """Extension guess from the output src when PIL cannot read the bytes."""
    src = new_src or ""
    if ".png" in src:
        return ".png"
    if ".jpg" in src or ".jpeg" in src:
        return ".jpg"
    if ".webp" in src:
        return ".webp"
    return ".png"


async def _block_validate(run: BatchRun, job: JobState, block: Any) -> None:
    """VALIDATE: PIL open; fallback to src-extension when lenient."""
    b = run.bridge
    if not job.file_bytes:
        raise RuntimeError("No file_bytes from download")
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(job.file_bytes))
        fmt = im.format or "PNG"
        job.ext = f".{fmt.lower()}" if fmt else ".png"
        if im.width == 0 or im.height == 0:
            raise ValueError("Zero dimension image")
        b._emit_job_action_status(job.job_id, block, "success", f"Valid {fmt} {im.width}x{im.height}")
    except Exception as e:
        job.ext = _fallback_ext(job.new_src)
        if len(job.file_bytes) < 100:
            raise RuntimeError(f"Validation failed: {e}")
        b._emit_job_action_status(job.job_id, block, "success", f"Validation fallback ext {job.ext}, bytes {len(job.file_bytes)}")


async def _block_save(run: BatchRun, job: JobState, block: Any) -> None:
    """SAVE: output path by naming rules, atomic write, highlight emit."""
    b = run.bridge
    if not job.file_bytes:
        raise RuntimeError("No file_bytes to save")
    source_path = Path(job.img.absolute_path)
    if not job.ext:
        job.ext = ".png"
    job.output_path = get_output_path(
        source_path,
        suffix=run.suffix,
        preserve_format=run.preserve_format,
        overwrite=run.overwrite,
        downloaded_ext=job.ext,
        unique_template=run.unique_tpl
    )
    atomic_write_bytes(source_path.parent, job.output_path, job.file_bytes)
    job.img.output_path = str(job.output_path)
    b._log(f"[{job.correlation_id}] ✅ Saved to {job.output_path} ({len(job.file_bytes)} bytes)", "success")
    try:
        b.highlight_rect.emit(json.dumps({"x": 100, "y": 100, "width": 200, "height": 200, "duration": run.highlight_duration, "label": f"Saved {job.output_path.name}"}))
    except Exception:
        pass
    b._emit_job_action_status(job.job_id, block, "success", f"Saved {job.output_path.name} {len(job.file_bytes)} bytes")


async def _block_advance(run: BatchRun, job: JobState, block: Any) -> None:
    """ADVANCE: mark completed, persist."""
    b = run.bridge
    job.img.status = ImageStatus.COMPLETED.value
    job.img.error = None
    b.state.recalculate_progress()
    b._save_arena()
    b._emit_job_action_status(job.job_id, block, "success", f"Advanced to completed")


_BLOCK_HANDLERS = {
    "CUSTOM_FIND": _block_custom_find,
    "HIGHLIGHT": _block_highlight,
    "PAUSE": _block_pause,
    "TYPE_PROMPT": _block_type_prompt,
    "OBSERVE_BASELINE": _block_baseline,
    "CHECK_SECURITY": _block_check_security,
    "HIGHLIGHT_ATTACH": _block_highlight_family,
    "HIGHLIGHT_PROMPT": _block_highlight_family,
    "HIGHLIGHT_SUBMIT": _block_highlight_family,
    "ATTACH_IMAGE": _block_attach,
    "VERIFY_ATTACHMENT": _block_verify_attachment,
    "INSERT_PROMPT": _block_insert_prompt,
    "VERIFY_PROMPT": _block_verify_prompt,
    "SUBMIT": _block_submit,
    "WAIT_OUTPUT": _block_wait,
    "AWAIT_PROCESSING_IMAGE": _block_wait,
    "DOWNLOAD": _block_download,
    "VALIDATE": _block_validate,
    "SAVE": _block_save,
    "ADVANCE": _block_advance,
}
