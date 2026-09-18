# ideal-size: ~490 lines reason=one block-runner owns all block handlers sharing JobCtx; splitting handlers across files would scatter one per-image lifecycle that always changes together (RULE 18.2)
"""Single job runner — small helpers per RULE 18/16."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.enums import ImageStatus
from app.core.naming import atomic_write_bytes, get_output_path
from app.browser.visual_click import ClickRequest, find_and_click

log = logging.getLogger("arena")


@dataclass
class JobCtx:
    """Context to keep params ≤4."""

    bridge: Any
    ctrl: Any
    client: Any
    tab_id: str
    img: Any
    urls: List[Any]
    job_id: str
    corr_id: str
    final_prompt: str
    baseline: Dict[str, Any] = field(default_factory=dict)
    new_src: Optional[str] = None
    file_bytes: Optional[bytes] = None
    ctype: Optional[str] = None
    old_srcs: List[str] = field(default_factory=list)


def _emit_action(ctx: JobCtx, block: Any, status: str, msg: str):
    """Emit action status."""
    try:
        ctx.bridge._emit_job_action_status(ctx.job_id, block, status, msg)
    except Exception:
        pass


def _get_blocks(ctx: JobCtx) -> List[Any]:
    """Get action blocks."""
    try:
        return ctx.bridge._get_action_blocks()
    except Exception:
        return []


async def capture_baseline(ctrl) -> Dict[str, Any]:
    """Capture baseline."""
    try:
        return await ctrl.capture_baseline()
    except Exception as e:
        log.warning(f"baseline {e}")
        return {"output_count": 0, "output_srcs": []}


def _handle_captcha_outcome(ctx: JobCtx, outcome: Any) -> None:
    """Map security outcomes without mistaking manual supersession for failure."""
    if outcome.status == "stopped":
        raise RuntimeError("Cancelled during CAPTCHA")
    if outcome.status == "page_error":
        raise RuntimeError(outcome.reason or "Page error during CAPTCHA")
    if outcome.status == "token_stale":
        try:
            ctx.bridge._log("⚠️ CAPTCHA API token stale; continuing page flow", "warn")
        except Exception:
            pass


async def check_security(ctx: JobCtx) -> bool:
    """Captcha gate: auto-solve (2Captcha, opt-in) else wait for user (RULE 20)."""
    try:
        visible = await ctx.ctrl.is_security_dialog_visible()
    except Exception:
        visible = False
    if not visible:
        return False
    from app.services.captcha import CaptchaCtx, handle_captcha

    def log(msg, level="info"):
        try:
            ctx.bridge._log(f"[{ctx.corr_id}] {msg}", level)
        except Exception:
            pass

    def stop():
        return bool(getattr(ctx.bridge, "_cancel_requested", False)) or _tab_aborted(ctx)

    outcome = await handle_captcha(CaptchaCtx(ctrl=ctx.ctrl, pool=getattr(ctx.bridge, "_page_pool", None),
                                              bridge=ctx.bridge, tab_id=ctx.tab_id,
                                              source="check-security", stop=stop, log=log))
    _handle_captcha_outcome(ctx, outcome)
    return True


def _mark_waiting(ctx: JobCtx, kind: str):
    """Mark waiting."""
    try:
        pool = ctx.bridge._ensure_page_pool()
        if pool:
            pool.mark_waiting(ctx.tab_id, kind)
            ctx.bridge._emit_pool_status()
    except Exception:
        pass


def _mark_busy(ctx: JobCtx):
    """Mark busy."""
    try:
        pool = ctx.bridge._ensure_page_pool()
        if pool:
            pool.mark_busy(ctx.tab_id, ctx.job_id)
            ctx.bridge._emit_pool_status()
    except Exception:
        pass


async def attach_image(ctx: JobCtx) -> tuple[bool, str]:
    """Attach image."""
    try:
        return await ctx.ctrl.attach_image(ctx.img.absolute_path)
    except Exception as e:
        return False, str(e)


async def insert_prompt(ctx: JobCtx) -> tuple[bool, str]:
    """Insert prompt."""
    try:
        return await ctx.ctrl.insert_prompt(ctx.final_prompt)
    except Exception as e:
        return False, str(e)


async def submit_job(ctx: JobCtx, block: Any) -> tuple[bool, str]:
    """Submit job."""
    try:
        ok, reason = await ctx.ctrl.submit()
        if ok:
            return True, reason
    except Exception:
        pass
    return await _submit_fallback(ctx, block)


async def _submit_fallback(ctx: JobCtx, block: Any) -> tuple[bool, str]:
    """Fallback click."""
    try:
        sel = getattr(block, "selector", "") or 'button[aria-label="Send message"]'
        req = ClickRequest(selector=sel, highlight_enabled=False, label="Submit")
        res = await find_and_click(ctx.client, req, engine=None)
        if res == "ok":
            return True, "Clicked via visual runner"
    except Exception as e:
        return False, f"Submit failed {e}"
    return False, "Submit failed"


async def wait_for_output(ctx: JobCtx, timeout_ms: int) -> tuple[Optional[str], Optional[bytes], str]:
    """Wait output."""
    try:
        await _show_gen_overlay(ctx, timeout_ms)
        _arm_revival(ctx)  # bounded resubmit if the blocked generation died
        ctx.ctrl.security_settler = lambda: _settle_and_note(ctx)  # captcha inside the wait
        status, data = await ctx.ctrl.wait_for_new_output(
            ctx.baseline, timeout_ms=timeout_ms, correlation_id=ctx.corr_id,
            cancel_check=lambda: _is_cancelled(ctx),
        )
        if isinstance(data, dict) and data.get("cancelled") and _tab_aborted(ctx):
            data["error"] = "Aborted by operator"
        src = data.get("new_src") if isinstance(data, dict) else None
        if status == "completed" and src:
            return await _verify_download(ctx, src)
        return await _hide_and_result(ctx, src, data)
    except Exception as e:
        await _hide_overlay(ctx)
        return None, None, str(e)
    finally:
        try:
            delattr(ctx.ctrl, "security_settler")
        except Exception:
            pass
        _clear_revival(ctx)


async def _settle_and_note(ctx: JobCtx):
    """Settle a mid-wait dialog, then stamp it for generation revival."""
    from app.services.captcha.recovery import note_settle
    settled = await check_security(ctx)
    if settled:
        note_settle(ctx.ctrl)
    return settled


def _report_recovery(ctx: JobCtx, msg: str, level: str = "info"):
    """Revival log with the job correlation prefix (RULE 2)."""
    try:
        ctx.bridge._log(f"[{ctx.corr_id}] {msg}", level)
    except Exception:
        pass


def _arm_revival(ctx: JobCtx):
    """Arm post-captcha revival for this generation wait (services-owned)."""
    from app.services.captcha.recovery import arm_resume
    try:
        policy = arm_resume(ctx.ctrl, ctx.final_prompt, cancelled=lambda: _is_cancelled(ctx),
                            report=lambda m, l="info": _report_recovery(ctx, m, l))
        img = getattr(ctx, "img", None)
        path = getattr(img, "absolute_path", None) if img is not None else None
        if path:
            policy.image_path = str(path)
    except Exception:
        pass


def _clear_revival(ctx: JobCtx):
    """Disarm revival at wait end; never raises."""
    from app.services.captcha.recovery import clear_resume
    try:
        clear_resume(ctx.ctrl)
    except Exception:
        pass


async def _show_gen_overlay(ctx: JobCtx, timeout_ms: int):
    """Show generation overlay."""
    try:
        gen_to = int(ctx.bridge.config.get_state("watcher_generation_timeout_sec", 600))
        eff = max(gen_to, int(timeout_ms / 1000)) if timeout_ms else 600
        await ctx.ctrl.show_watcher_overlay("wait for finish generation", kind="generation", timeout_sec=eff)
        _mark_waiting(ctx, "generation")
    except Exception:
        pass


async def _verify_download(ctx: JobCtx, src: str):
    """Verify downloadable."""
    await asyncio.sleep(3)
    try:
        s, f, c = await ctx.ctrl.download_image(src)
        if s and f and len(f) > 100:
            await _hide_overlay(ctx)
            _mark_busy(ctx)
            return src, f, c
    except Exception:
        pass
    await _hide_overlay(ctx)
    _mark_busy(ctx)
    return src, None, "not downloadable"


async def _hide_and_result(ctx: JobCtx, src, data):
    """Hide overlay and return result."""
    await _hide_overlay(ctx)
    _mark_busy(ctx)
    if src:
        return src, None, "not downloadable"
    err = data.get("error", "timeout") if isinstance(data, dict) else "timeout"
    return None, None, str(err)


async def _hide_overlay(ctx: JobCtx):
    """Hide overlay."""
    try:
        await ctx.ctrl.hide_watcher_overlay()
    except Exception:
        pass


async def download_image(ctx: JobCtx, src: str) -> tuple[bool, bytes, str]:
    """Download."""
    try:
        return await ctx.ctrl.download_image(src)
    except Exception as e:
        return False, b"", str(e)


async def save_image(ctx: JobCtx, file_bytes: bytes) -> Optional[Path]:
    """Save atomically."""
    try:
        settings = ctx.bridge.state.settings
        suffix = settings.output.get("suffix", "_AI")
        overwrite = settings.output.get("overwrite", False)
        preserve = settings.output.get("preserve_format", True)
        tpl = settings.output.get("unique_suffix_template", "{base}_AI_{n}{ext}")
        ext = ".png"
        src_path = Path(ctx.img.absolute_path)
        out_path = get_output_path(src_path, suffix=suffix, preserve_format=preserve, overwrite=overwrite, downloaded_ext=ext, unique_template=tpl)
        atomic_write_bytes(src_path.parent, out_path, file_bytes)
        return out_path
    except Exception as e:
        log.warning(f"save {e}")
        return None


# ---- block handlers each small ----

async def _handle_baseline(ctx: JobCtx, block: Any):
    """Handle baseline."""
    ctx.baseline = await capture_baseline(ctx.ctrl)
    try:
        ctx.old_srcs = list(ctx.baseline.get("output_srcs", []) or [])
    except Exception:
        ctx.old_srcs = []
    _emit_action(ctx, block, "success", f"Baseline {ctx.baseline.get('output_count')}")


async def _handle_security(ctx: JobCtx, block: Any):
    """Handle security."""
    await check_security(ctx)
    _emit_action(ctx, block, "success", "Security done")


async def _handle_attach(ctx: JobCtx, block: Any):
    """Handle attach."""
    ok, reason = await attach_image(ctx)
    if not ok:
        raise RuntimeError(f"Attach failed: {reason}")
    _emit_action(ctx, block, "success", reason)


async def _handle_prompt(ctx: JobCtx, block: Any):
    """Handle prompt."""
    ok, reason = await insert_prompt(ctx)
    if not ok:
        raise RuntimeError(f"Prompt failed: {reason}")
    _emit_action(ctx, block, "success", reason)


async def _handle_submit(ctx: JobCtx, block: Any):
    """Handle submit."""
    ok, reason = await submit_job(ctx, block)
    if not ok:
        raise RuntimeError(f"Submit failed: {reason}")
    _emit_action(ctx, block, "success", reason)
    await check_security(ctx)  # F4: captcha often pops at submit time


async def _handle_wait(ctx: JobCtx, block: Any):
    """Handle wait."""
    timeout = getattr(block, "timeout_ms", 0) or ctx.bridge.state.settings.timeouts.get("generation", 180) * 1000
    src, fbytes, err = await wait_for_output(ctx, timeout)
    if src:
        ctx.new_src = src
    if fbytes:
        ctx.file_bytes = fbytes
        ctx.ctype = "image"
    is_await = getattr(block, "block_id", "") == "AWAIT_PROCESSING_IMAGE"
    if not ctx.new_src and not is_await:
        raise RuntimeError(f"Wait failed: {err}")
    _emit_action(ctx, block, "success", f"Output {ctx.new_src[:60] if ctx.new_src else 'done'}")


async def _handle_download(ctx: JobCtx, block: Any):
    """Handle download."""
    await check_security(ctx)  # F4: catch a captcha before pulling bytes
    if ctx.file_bytes and len(ctx.file_bytes) > 100:
        _emit_action(ctx, block, "success", f"Already {len(ctx.file_bytes)}")
        return
    if not ctx.new_src:
        raise RuntimeError("No new_src")
    await asyncio.sleep(3)
    s, f, c = await download_image(ctx, ctx.new_src)
    if not s or len(f) < 100:
        raise RuntimeError(f"Download failed: {c}")
    ctx.file_bytes = f
    ctx.ctype = c
    _emit_action(ctx, block, "success", f"Downloaded {len(f)}")


async def _handle_validate(ctx: JobCtx, block: Any):
    """Handle validate."""
    if not ctx.file_bytes:
        raise RuntimeError("No bytes")
    _emit_action(ctx, block, "success", f"Valid {len(ctx.file_bytes)}")


async def _handle_save(ctx: JobCtx, block: Any):
    """Handle save."""
    if not ctx.file_bytes:
        raise RuntimeError("No bytes to save")
    out = await save_image(ctx, ctx.file_bytes)
    if not out:
        raise RuntimeError("Save failed")
    ctx.img.output_path = str(out)
    _emit_action(ctx, block, "success", f"Saved {out.name}")


async def _handle_advance(ctx: JobCtx, block: Any):
    """Handle advance."""
    ctx.img.status = ImageStatus.COMPLETED.value
    _emit_action(ctx, block, "success", "Completed")


async def _handle_custom(ctx: JobCtx, block: Any):
    """Handle custom find."""
    try:
        req = ClickRequest(
            selector=getattr(block, "selector", "") or "button",
            label_selector=getattr(block, "label_selector", "") or "",
            match_text=getattr(block, "match_text", "") or "",
            click_enabled=getattr(block, "click_enabled", True),
            highlight_enabled=getattr(block, "highlight_enabled", True),
            label=getattr(block, "display_name", ""),
        )
        res = await find_and_click(ctx.client, req, engine=ctx.bridge)
        if res == "ok":
            _emit_action(ctx, block, "success", f"FIND ok {block.selector}")
        else:
            raise RuntimeError(f"Find failed {block.selector}")
    except Exception as e:
        raise RuntimeError(f"CUSTOM_FIND failed: {e}")


def _handler_map():
    """Map block_id to handler."""
    return {
        "OBSERVE_BASELINE": _handle_baseline,
        "CHECK_SECURITY": _handle_security,
        "ATTACH_IMAGE": _handle_attach,
        "INSERT_PROMPT": _handle_prompt,
        "SUBMIT": _handle_submit,
        "WAIT_OUTPUT": _handle_wait,
        "AWAIT_PROCESSING_IMAGE": _handle_wait,
        "DOWNLOAD": _handle_download,
        "VALIDATE": _handle_validate,
        "SAVE": _handle_save,
        "ADVANCE": _handle_advance,
        "CUSTOM_FIND": _handle_custom,
    }


async def _handle_one_block(ctx: JobCtx, block: Any):
    """Dispatch one block."""
    hmap = _handler_map()
    btype = getattr(block, "block_id", "")
    handler = hmap.get(btype)
    if handler:
        await handler(ctx, block)
    else:
        _emit_action(ctx, block, "success", f"Skipped {btype}")


def _init_old_srcs(ctx: JobCtx):
    try:
        ctx.old_srcs = list(ctx.baseline.get("output_srcs", []) or [])
    except Exception:
        ctx.old_srcs = []


async def _maybe_delay(block: Any):
    d = getattr(block, "pre_delay_ms", 0)
    if d:
        await asyncio.sleep(d / 1000.0)


def _tab_aborted(ctx: JobCtx) -> bool:
    """Operator stop requested for this tab's job."""
    try:
        from .cooldown_service import is_tab_aborted
        return is_tab_aborted(getattr(ctx.bridge, "_page_pool", None), ctx.tab_id)
    except Exception:
        return False


def _is_cancelled(ctx: JobCtx) -> bool:
    return bool(getattr(ctx.bridge, "_cancel_requested", False)) or _tab_aborted(ctx)


async def _run_one_checked(ctx: JobCtx, block: Any) -> tuple[bool, str, bool]:
    if _is_cancelled(ctx):
        return True, "Aborted by operator" if _tab_aborted(ctx) else "Cancelled", True
    if not getattr(block, "enabled", True):
        return False, "", False
    await _maybe_delay(block)
    try:
        _emit_action(ctx, block, "running", f"[{ctx.tab_id[:6]}] {block.display_name}")
    except Exception:
        pass
    try:
        await _handle_one_block(ctx, block)
        return False, "", False
    except Exception as e:
        err = str(e)
        try:
            _emit_action(ctx, block, "failed", err)
        except Exception:
            pass
        should_break = bool(getattr(block, "required", False))
        return True, err, should_break


async def _loop_blocks(ctx: JobCtx, blocks: List[Any]) -> tuple[bool, str]:
    failed = False
    error = ""
    for block in blocks:
        f, e, brk = await _run_one_checked(ctx, block)
        if f:
            failed = True
            error = e
            if brk:
                break
        if _is_cancelled(ctx) and failed:
            break
    return failed, error


def _reset_captcha_reports(ctx: JobCtx):
    """Drop stale encounter stash (a reused ctrl must not leak reports)."""
    try:
        ctx.ctrl._captcha_reports = []
    except Exception:
        pass


def _captcha_job_line(ctx: JobCtx, entry: Dict[str, Any], failed: bool, error: str) -> Dict[str, Any]:
    """One CAPTCHA_JOB join record for a stashed encounter."""
    perr = error if "Page error:" in (error or "") else ""
    return {"v": 1, "eid": entry.get("eid", ""), "corr": ctx.corr_id,
            "tab": entry.get("tab", ctx.tab_id),
            "image": getattr(ctx.img, "relative_path", "") or "",
            "job": "failed" if failed else "completed",
            "error": str(error or "")[:200], "page_error": perr[:200]}


def _emit_captcha_job_lines(ctx: JobCtx, failed: bool, error: str) -> None:
    """Drain the encounter stash (each eid reported exactly once)."""
    try:
        lst = getattr(ctx.ctrl, "_captcha_reports", None)
        if not isinstance(lst, list) or not lst:
            return
        ctx.ctrl._captcha_reports = []
    except Exception:
        return
    for entry in lst:
        try:
            line = _captcha_job_line(ctx, entry if isinstance(entry, dict) else {}, failed, error)
            ctx.bridge._log(f"[{ctx.corr_id}] 🧾 CAPTCHA_JOB {json.dumps(line, ensure_ascii=False)}", "info")
        except Exception:
            pass


def _stop_captcha_recording(ctx: JobCtx, failed: bool, error: str) -> None:
    """Close the recording at the actual image-job terminal result."""
    session = getattr(ctx.ctrl, "_captcha_recording", None)
    if session is None:
        return
    try:
        session.event("job_outcome", {"status": "failed" if failed else "completed",
                                       "error": str(error or "")[:200]})
        session.stop("job_terminal", "failed" if failed else "completed")
        delattr(ctx.ctrl, "_captcha_recording")
    except Exception:
        pass


async def run_blocks_for_image(ctx: JobCtx) -> tuple[bool, str, Optional[str], Optional[bytes]]:
    blocks = _get_blocks(ctx)
    _init_old_srcs(ctx)
    _reset_captcha_reports(ctx)
    failed, error = await _loop_blocks(ctx, blocks)
    _stop_captcha_recording(ctx, failed, error)
    _emit_captcha_job_lines(ctx, failed, error)
    return failed, error, ctx.new_src, ctx.file_bytes
