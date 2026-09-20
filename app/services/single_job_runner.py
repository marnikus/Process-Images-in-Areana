# ideal-size: ~830 lines reason=single converged block-runner owns the block handlers sharing JobCtx; splitting handlers across files would scatter one per-image lifecycle that always changes together (RULE 18.2). AWAIT_PROCESSING_IMAGE lives in services/await_processing.py (B12): it is a different mechanism (indicator poll, never fails), not a variant of the new-output wait.
"""Single job runner — small helpers per RULE 18/16."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.enums import ImageStatus
from app.core.naming import OutputSpec, atomic_write_bytes, get_output_path
from app.browser.dom_highlight import build_find_probe, build_highlight_probe
from app.browser.probe_selectors import (
    send_click_primary,
    send_presence_selector,
    textarea_primary,
)
from app.browser.site_adapter import get_selector
from app.browser.probe_requests import FindProbeSpec, HighlightSpec
from app.browser.visual_click import ClickRequest, find_and_click
from app.services.await_processing import handle_await_processing
from app.core.pause_clock import PauseClock
from app.services.captcha.policy import captcha_in_scope, pause_cap_seconds
from app.services.run_state import JobAction

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
    ext: Optional[str] = None
    old_srcs: List[str] = field(default_factory=list)


def _emit_action(ctx: JobCtx, block: Any, status: str, msg: str):
    """Emit action status."""
    try:
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, status, msg))
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


_CAPTCHA_FAILURES = {  # status → job-failure text (RuntimeError ⇒ the normal retryable path)
    "stopped": "Cancelled during CAPTCHA",
    "page_error": "Page error during CAPTCHA",
    "wait_timeout": "Captcha wait hit the cap",   # D-14R: no penalty, cooldown as usual
}


def _captcha_failure_text(outcome: Any) -> Optional[str]:
    """The failure text for a failing captcha outcome (None = not a failure); stop keeps its fixed text."""
    default = _CAPTCHA_FAILURES.get(outcome.status)
    if default is None or outcome.status == "stopped":
        return default
    return outcome.reason or default


def _handle_captcha_outcome(ctx: JobCtx, outcome: Any) -> None:
    """Map security outcomes without mistaking manual supersession for failure."""
    failure = _captcha_failure_text(outcome)
    if failure:
        raise RuntimeError(failure)
    if outcome.status == "token_stale":
        try:
            ctx.bridge._log("⚠️ CAPTCHA API token stale; continuing page flow", "warn")
        except Exception:
            pass


async def _run_security_captcha(ctx: JobCtx) -> None:
    """Solve/handle the visible security dialog (closures + outcome)."""
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


async def check_security(ctx: JobCtx) -> bool:
    """Captcha gate (RULE 20): out of scope while the Watcher is OFF, else wait."""
    if not captcha_in_scope(ctx.bridge):
        return False
    try:
        visible = await ctx.ctrl.is_security_dialog_visible()
    except Exception:
        visible = False
    if not visible:
        return False
    await _run_security_captcha(ctx)
    return True


def _mark_waiting(ctx: JobCtx, kind: str):
    """Mark waiting (pool attr; the old _ensure_page_pool call never existed)."""
    try:
        pool = getattr(ctx.bridge, "_page_pool", None)
        if pool:
            pool.mark_waiting(ctx.tab_id, kind)
            ctx.bridge._emit_pool_status()
    except Exception:
        pass


def _mark_busy(ctx: JobCtx):
    """Mark busy."""
    try:
        pool = getattr(ctx.bridge, "_page_pool", None)
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


def _display(block: Any) -> str:
    """Block display name (ActionBlock or bare stub)."""
    name = getattr(block, "display_name", "") or getattr(block, "name", "")
    if callable(name):
        try:
            name = name()
        except Exception:
            name = ""
    return name or getattr(block, "block_id", "block")


def _click_req(block: Any, sel: str, text: str) -> ClickRequest:
    """Visual-runner request from block fields (RULE 1)."""
    return ClickRequest(
        selector=sel,
        label_selector=getattr(block, "label_selector", "") or "",
        match_text=text,
        match_mode=getattr(block, "match_mode", "") or "contains",
        click_enabled=getattr(block, "click_enabled", True),
        click_selector=getattr(block, "click_selector", "") or "",
        highlight_enabled=getattr(block, "highlight_enabled", True),
        confirm_pause_ms=getattr(block, "confirm_pause_ms", 0) or 700,
        highlight_ms=getattr(block, "highlight_ms", 0) or 2000,
        label=_display(block),
    )


def _fallback_list(block: Any) -> List[str]:
    """Comma-separated fallback selectors, blanks dropped."""
    raw = getattr(block, "fallback_selector", "") or ""
    return [s.strip() for s in raw.split(",") if s.strip()]


async def _try_click(ctx: JobCtx, req: ClickRequest) -> str:
    """One visual attempt; never raises (returns 'fail' instead)."""
    try:
        return await find_and_click(ctx.client, req, engine=ctx.bridge)
    except Exception:
        return "fail"


async def _submit_visual(ctx: JobCtx, block: Any) -> str:
    """Primary submit click through the visual runner."""
    sel = getattr(block, "selector", "") or send_click_primary()
    return await _try_click(ctx, _click_req(block, sel, getattr(block, "match_text", "") or ""))


async def _submit_fallbacks(ctx: JobCtx, block: Any) -> Optional[str]:
    """Fallback selectors in order; first 'ok' wins."""
    for fb_sel in _fallback_list(block):
        _report_recovery(ctx, f"↩ Submit fallback trying {fb_sel[:40]}", "warn")
        req = _click_req(block, fb_sel, getattr(block, "fallback_text", "") or "")
        req = replace(req, label=f"Submit fallback {fb_sel[:40]}")
        if await _try_click(ctx, req) == "ok":
            return fb_sel
    return None


async def submit_job(ctx: JobCtx, block: Any) -> tuple[bool, str]:
    """Submit: visual first, fallbacks, controller last resort."""
    if await _submit_visual(ctx, block) == "ok":
        sel = getattr(block, "selector", "") or "submit"
        return True, f"Clicked {sel}"
    won = await _submit_fallbacks(ctx, block)
    if won:
        return True, f"Submit via fallback {won}"
    try:
        ok, reason = await ctx.ctrl.submit()
        if ok:
            return True, f"Submit via controller {reason}"
        return False, f"Submit failed: {reason}"
    except Exception as e:
        return False, f"Submit failed: {e}"


async def _poll_generation(ctx: JobCtx, timeout_ms: int):
    """Poll for new output; (status, data, src) with abort marking."""
    status, data = await ctx.ctrl.wait_for_new_output(
        ctx.baseline, timeout_ms=timeout_ms, correlation_id=ctx.corr_id,
        cancel_check=lambda: _is_cancelled(ctx),
    )
    if isinstance(data, dict) and data.get("cancelled") and _tab_aborted(ctx):
        data["error"] = "Aborted by operator"
    src = data.get("new_src") if isinstance(data, dict) else None
    return status, data, src


def _install_wait_hooks(ctx: JobCtx) -> None:
    """Captcha inside the wait — Watcher ON only (I-48): the settler + the capped pause clock (D-14R)."""
    if not captcha_in_scope(ctx.bridge):
        return
    ctx.ctrl.security_settler = lambda: _settle_and_note(ctx)
    ctx.ctrl.pause_clock = PauseClock(pause_cap_seconds(ctx.bridge))


def _uninstall_wait_hooks(ctx: JobCtx) -> None:
    """Drop the per-wait ctrl hooks (absent on the OFF path — nothing to drop)."""
    for name in ("security_settler", "pause_clock"):
        try:
            delattr(ctx.ctrl, name)
        except Exception:
            pass


async def wait_for_output(ctx: JobCtx, timeout_ms: int) -> tuple[Optional[str], Optional[bytes], str]:
    """Wait output."""
    try:
        await _show_gen_overlay(ctx, timeout_ms)
        _arm_revival(ctx)  # bounded resubmit if the blocked generation died
        _install_wait_hooks(ctx)
        status, data, src = await _poll_generation(ctx, timeout_ms)
        if status == "completed" and src:
            return await _verify_download(ctx, src)
        return await _hide_and_result(ctx, src, data)
    except Exception as e:
        await _hide_overlay(ctx)
        return None, None, str(e)
    finally:
        _uninstall_wait_hooks(ctx)
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
    """Save atomically (validated ext or .png)."""
    try:
        settings = ctx.bridge.state.settings
        suffix = settings.output.get("suffix", "_AI")
        overwrite = settings.output.get("overwrite", False)
        preserve = settings.output.get("preserve_format", True)
        tpl = settings.output.get("unique_suffix_template", "{base}_AI_{n}{ext}")
        ext = getattr(ctx, "ext", None) or ".png"
        src_path = Path(ctx.img.absolute_path)
        spec = OutputSpec(suffix=suffix, preserve_format=preserve, overwrite=overwrite,
                          downloaded_ext=ext, unique_template=tpl)
        out_path = get_output_path(src_path, spec)
        atomic_write_bytes(src_path.parent, out_path, file_bytes)
        _emit_saved_rect(ctx, out_path.name)
        return out_path
    except Exception as e:
        log.warning(f"save {e}")
        return None


def _emit_saved_rect(ctx: JobCtx, name: str):
    """Saved-file confirmation rect (best effort, UI only)."""
    try:
        dur = ctx.bridge.config.get_state("highlight_duration", 3)
        payload = {"x": 100, "y": 100, "width": 200, "height": 200,
                   "duration": dur, "label": f"Saved {name}"}
        ctx.bridge.highlight_rect.emit(json.dumps(payload))
    except Exception:
        pass


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
    """Handle security (announce while solving, like the legacy loop)."""
    if not captcha_in_scope(ctx.bridge):
        _emit_action(ctx, block, "success", "Skipped (Watcher off)")
        return
    try:
        visible = await ctx.ctrl.is_security_dialog_visible()
    except Exception:
        visible = False
    if visible:
        _emit_action(ctx, block, "running", "Security dialog visible — solving or waiting")
    await check_security(ctx)
    _emit_action(ctx, block, "success", "Security done")


async def _attach_open_dialog(ctx: JobCtx, block: Any):
    """Human-like file-dialog click before attach (best effort)."""
    if not (getattr(block, "click_selector", "") and getattr(block, "click_enabled", False)):
        return
    try:
        req = _click_req(block, block.click_selector, "")
        req = replace(req, label=f"{_display(block)} open dialog")
        await _try_click(ctx, req)
        await asyncio.sleep(0.5)
    except Exception as e:
        _report_recovery(ctx, f"Open dialog click skipped: {e}", "warn")


async def _attach_emit(ctx: JobCtx, block: Any, reason: str):
    """Attach success, with confirmation rect when highlight works."""
    try:
        sel = getattr(block, "selector", "") or get_selector("file_input").presence()
        color = getattr(block, "color", "") or "#FF0000"
        ms = getattr(block, "highlight_ms", 0) or 2000
        rect = await ctx.ctrl.highlight_selector(sel, color=color, duration_ms=ms, caption="Attached ok")
        rd = rect.get("rect", rect) if isinstance(rect, dict) else None
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", reason, rd))
    except Exception:
        _emit_action(ctx, block, "success", reason)


async def _handle_attach(ctx: JobCtx, block: Any):
    """Handle attach."""
    await _attach_open_dialog(ctx, block)
    ok, reason = await attach_image(ctx)
    if not ok:
        raise RuntimeError(f"Attach failed: {reason}")
    _report_recovery(ctx, f"Attachment verified: {reason}", "success")
    await _attach_emit(ctx, block, reason)


async def _handle_prompt(ctx: JobCtx, block: Any):
    """Handle prompt."""
    ok, reason = await insert_prompt(ctx)
    if not ok:
        raise RuntimeError(f"Prompt failed: {reason}")
    _emit_action(ctx, block, "success", reason)


async def _handle_submit(ctx: JobCtx, block: Any):
    """Handle submit (settle React, then visual-first submit)."""
    await asyncio.sleep(0.8)  # let React enable the button after prompt insert
    ok, reason = await submit_job(ctx, block)
    if not ok:
        raise RuntimeError(reason)
    _emit_action(ctx, block, "success", reason)
    await check_security(ctx)  # F4: captcha often pops at submit time


async def _handle_wait(ctx: JobCtx, block: Any):
    """WAIT_OUTPUT: announce, then wait for the NEW output image (legacy loop).

    B12: AWAIT_PROCESSING_IMAGE no longer shares this handler — the new-output
    wait can only end by timeout on an idle page (services/await_processing)."""
    timeout = getattr(block, "timeout_ms", 0) or ctx.bridge.state.settings.timeouts.get("generation", 180) * 1000
    _emit_action(ctx, block, "running", f"Waiting for generation — timeout {timeout}ms")
    src, fbytes, err = await wait_for_output(ctx, timeout)
    if src:
        ctx.new_src = src
    if fbytes:
        ctx.file_bytes = fbytes
        ctx.ctype = "image"
    if not ctx.new_src:
        raise RuntimeError(f"Wait failed: {err}")
    _emit_action(ctx, block, "success", f"Output {ctx.new_src[:60]}")


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


def _pil_format(data: bytes) -> Optional[str]:
    """Lowercase PIL format when bytes decode to a sized image."""
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data))
        if im.width and im.height:
            return (im.format or "PNG").lower()
    except Exception:
        return None
    return None


def _src_suffix(src: str) -> str:
    """Extension hint from the source URL (last resort: .png)."""
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        if suffix in (src or ""):
            return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


def _infer_ext(ctx: JobCtx) -> str:
    """Image ext from bytes (PIL) or src suffix; raises when too small."""
    fmt = _pil_format(ctx.file_bytes or b"")
    if fmt:
        return f".{fmt}"
    if len(ctx.file_bytes or b"") < 100:
        raise RuntimeError("Validation failed: unreadable image")
    return _src_suffix(ctx.new_src or "")


async def _handle_validate(ctx: JobCtx, block: Any):
    """Handle validate (sets ctx.ext for SAVE)."""
    if not ctx.file_bytes:
        raise RuntimeError("No bytes")
    ctx.ext = _infer_ext(ctx)
    _emit_action(ctx, block, "success", f"Valid {ctx.ext} {len(ctx.file_bytes)} bytes")


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


async def _custom_ok_emit(ctx: JobCtx, block: Any, sel: str):
    """Custom-find success, with confirmation rect when highlight works."""
    try:
        ms = getattr(block, "highlight_ms", 0) or 2000
        rect = await ctx.ctrl.highlight_selector(sel, color=getattr(block, "color", "") or "#FF0000", duration_ms=ms, caption=_display(block))
        rd = rect.get("rect", rect) if isinstance(rect, dict) else None
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", f"FIND+CLICK ok {sel}", rd))
    except Exception:
        _emit_action(ctx, block, "success", f"FIND+CLICK ok {sel}")


async def _custom_fallbacks(ctx: JobCtx, block: Any) -> Optional[str]:
    """Fallback selectors in order; first 'ok' wins."""
    for fb_sel in _fallback_list(block):
        _report_recovery(ctx, f"↩ Trying fallback {fb_sel[:40]}", "warn")
        req = _click_req(block, fb_sel, getattr(block, "fallback_text", "") or "")
        req = replace(req, click_enabled=True,
                      label=f"{_display(block)} fallback {fb_sel[:30]}")
        if await _try_click(ctx, req) == "ok":
            return fb_sel
    return None


async def _handle_custom(ctx: JobCtx, block: Any):
    """Handle custom find (primary + fallbacks, legacy parity)."""
    sel = getattr(block, "selector", "") or "button"
    req = _click_req(block, sel, getattr(block, "match_text", "") or "")
    if await _try_click(ctx, req) == "ok":
        await _custom_ok_emit(ctx, block, sel)
        return
    won = await _custom_fallbacks(ctx, block)
    if won:
        _emit_action(ctx, block, "success", f"Fallback ok {won}")
        return
    tried = _fallback_list(block)
    if tried:
        raise RuntimeError(f"Find & Click failed for {sel} and fallbacks {tried}")
    raise RuntimeError(f"Find & Click failed for {sel}")


def _str(block: Any, name: str, default: str) -> str:
    """Block text field with default for missing-or-empty."""
    val = getattr(block, name, "")
    return val if val else default


def _highlight_spec(block: Any, sel: str) -> HighlightSpec:
    """Probe spec from block fields (pure visual, no click)."""
    return HighlightSpec(
        label_selector=getattr(block, "label_selector", "") or None,
        match_text=getattr(block, "match_text", "") or None,
        match_mode=_str(block, "match_mode", "contains"),
        color=_str(block, "color", "#00c853"),
        caption=_display(block) or sel[:30],
        highlight_ms=getattr(block, "highlight_ms", 0) or 2000,
        clear_first=True,
    )


async def _handle_highlight(ctx: JobCtx, block: Any):
    """Pure visual confirmation (no click, legacy parity)."""
    sel = _str(block, "selector", "div")
    try:
        raw = await ctx.client.evaluate(build_highlight_probe(sel, _highlight_spec(block, sel)))
        res = json.loads(raw) if raw else {}
    except Exception as e:
        raise RuntimeError(f"Highlight failed: {e}")
    if not res.get("found"):
        raise RuntimeError(f"Highlight not found: {sel}")
    _report_recovery(ctx, f"Highlighted {sel}", "success")
    ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", f"Highlighted {sel}", res.get("rect")))


async def _handle_pause(ctx: JobCtx, block: Any):
    """Handle pause (duration from extra/timeout, legacy parity)."""
    extra = getattr(block, "extra", {}) or {}
    dur = extra.get("duration_ms") or getattr(block, "timeout_ms", 0) or 1000
    _report_recovery(ctx, f"⏸ Pausing {dur}ms", "info")
    await asyncio.sleep(dur / 1000.0)
    _emit_action(ctx, block, "success", f"Paused {dur}ms")


async def _type_highlight(ctx: JobCtx, block: Any) -> None:
    """Best-effort highlight before typed prompt (never fails)."""
    if not getattr(block, "highlight_enabled", False):
        return
    try:
        sel = getattr(block, "selector", "") or textarea_primary()
        await ctx.ctrl.highlight_selector(sel, color=getattr(block, "color", "") or "#FF0000", duration_ms=getattr(block, "highlight_ms", 0) or 2000, caption=_display(block))
    except Exception:
        pass


async def _handle_type_prompt(ctx: JobCtx, block: Any):
    """Handle typed prompt (highlight, then insert full prompt)."""
    extra = getattr(block, "extra", {}) or {}
    speed = extra.get("typing_speed_ms", 10)
    _report_recovery(ctx, f"⌨ Typing prompt speed {speed}ms", "info")
    await _type_highlight(ctx, block)
    ok, reason = await insert_prompt(ctx)
    if not ok:
        raise RuntimeError(f"Type prompt failed: {reason}")
    _emit_action(ctx, block, "success", reason)


def attachment_preview_selector() -> str:
    """Preview-image probe selector (RULE 21: container from site_adapter)."""
    return get_selector("attachment_preview_container").primary + " img"


def _marker_selector(block: Any) -> str:
    """Default selector per HIGHLIGHT_* marker (legacy parity)."""
    if getattr(block, "selector", ""):
        return block.selector
    btype = getattr(block, "block_id", "")
    if "ATTACH" in btype:
        return get_selector("file_input").presence()
    if "PROMPT" in btype:
        return textarea_primary()
    return send_presence_selector()


async def _handle_marker_highlight(ctx: JobCtx, block: Any):
    """Marker highlight: visual only, never fails the job."""
    try:
        sel = _marker_selector(block)
        ms = getattr(block, "highlight_ms", 0) or getattr(block, "highlight_duration_ms", 0) or 2000
        rect = await ctx.ctrl.highlight_selector(sel, color=getattr(block, "color", "") or "#FF0000", duration_ms=ms, caption=_display(block))
        rd = rect.get("rect", rect) if isinstance(rect, dict) else None
        ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", f"Highlighted {sel}", rd))
    except Exception as e:
        _emit_action(ctx, block, "success", f"Highlight skipped: {e}")


async def _handle_verify_attachment(ctx: JobCtx, block: Any):
    """Handle attachment-preview check (find probe, legacy parity)."""
    sel = getattr(block, "selector", "") or attachment_preview_selector()
    spec = FindProbeSpec(highlight=getattr(block, "highlight_enabled", True), highlight_ms=getattr(block, "highlight_ms", 0) or 1500, color=getattr(block, "color", "") or "#FF0000")
    try:
        raw = await ctx.client.evaluate(build_find_probe(sel, spec))
        res = json.loads(raw) if raw else {}
    except Exception as e:
        raise RuntimeError(f"Verify attachment failed: {e}")
    if not res.get("found"):
        raise RuntimeError(f"Verify attachment failed: preview not found {sel}")
    ctx.bridge._emit_job_action_status(JobAction(ctx.job_id, block, "success", f"Attachment preview found {sel}", res.get("rect")))


async def _handle_verify_prompt(ctx: JobCtx, block: Any):
    """Handle prompt check (one retry, legacy parity)."""
    verified, reason = await ctx.ctrl.verify_prompt(ctx.final_prompt)
    if not verified:
        _report_recovery(ctx, f"Prompt mismatch {reason}, retrying", "warn")
        await ctx.ctrl.insert_prompt(ctx.final_prompt)
        verified, reason = await ctx.ctrl.verify_prompt(ctx.final_prompt)
        if not verified:
            raise RuntimeError(f"Prompt verification failed: {reason}")
    _emit_action(ctx, block, "success", f"Verified {reason}")


def _handler_map():
    """Map block_id to handler (20 block types converged)."""
    # ideals-TABLED (R10.9): flat registry literal; splitting the dict
    # would scatter the A2 converge map across helpers with no seam.
    return {
        "OBSERVE_BASELINE": _handle_baseline,
        "CHECK_SECURITY": _handle_security,
        "HIGHLIGHT_ATTACH": _handle_marker_highlight,
        "ATTACH_IMAGE": _handle_attach,
        "VERIFY_ATTACHMENT": _handle_verify_attachment,
        "HIGHLIGHT_PROMPT": _handle_marker_highlight,
        "INSERT_PROMPT": _handle_prompt,
        "VERIFY_PROMPT": _handle_verify_prompt,
        "HIGHLIGHT_SUBMIT": _handle_marker_highlight,
        "SUBMIT": _handle_submit,
        "WAIT_OUTPUT": _handle_wait,
        "AWAIT_PROCESSING_IMAGE": handle_await_processing,
        "DOWNLOAD": _handle_download,
        "VALIDATE": _handle_validate,
        "SAVE": _handle_save,
        "ADVANCE": _handle_advance,
        "CUSTOM_FIND": _handle_custom,
        "HIGHLIGHT": _handle_highlight,
        "PAUSE": _handle_pause,
        "TYPE_PROMPT": _handle_type_prompt,
    }


async def _handle_one_block(ctx: JobCtx, block: Any):
    """Dispatch one block (unknown types skip, legacy parity)."""
    hmap = _handler_map()
    btype = getattr(block, "block_id", "")
    handler = hmap.get(btype)
    if handler:
        await handler(ctx, block)
    else:
        _report_recovery(ctx, f"Unknown block type {btype}, skipping", "warn")
        _emit_action(ctx, block, "skipped", f"Unknown type {btype}")


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


def _block_skip_reason(ctx: JobCtx, block: Any):
    """Cancellation/disabled short-circuit result, or None to run."""
    if _is_cancelled(ctx):
        reason = "Aborted by operator" if _tab_aborted(ctx) else "Cancelled by user"
        return True, reason, True
    if not getattr(block, "enabled", True):
        _emit_action(ctx, block, "skipped", "Skipped (disabled)")
        return False, "", False
    return None


async def _run_one_checked(ctx: JobCtx, block: Any) -> tuple[bool, str, bool]:
    skip = _block_skip_reason(ctx, block)
    if skip is not None:
        return skip
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


def _output_secured(ctx: JobCtx) -> bool:
    """The generated image is already in memory (DOWNLOAD/WAIT delivered bytes)."""
    return bool(ctx.file_bytes and len(ctx.file_bytes) > 100)


# Blocks whose failure means the secured bytes themselves are bad or unsaved.
_OUTPUT_BLOCKS = frozenset({"VALIDATE", "SAVE"})


def _post_download_warning(ctx: JobCtx, block: Any, err: str, secured: bool) -> bool:
    """B8 policy: once the image is downloaded, a later page-action failure is
    a warning, not a job failure — the stack continues so VALIDATE/SAVE keep
    the bytes (a paid generation is never thrown away). VALIDATE/SAVE and
    cancellation keep their normal failure semantics."""
    if not secured or _is_cancelled(ctx):
        return False
    if getattr(block, "block_id", "") in _OUTPUT_BLOCKS:
        return False
    name = getattr(block, "display_name", None) or getattr(block, "block_id", "block")
    _report_recovery(ctx, f"⚠ {name} failed after the image was downloaded ({err}) "
                          f"— continuing so the image is saved", "warn")
    return True


def _record_failure(block: Any, err: str, brk: bool, acc: Dict[str, Any]) -> bool:
    """Classify one block failure into the run accumulator; True = stop the stack.

    hard: a required break or a VALIDATE/SAVE failure (never forgiven);
    soft: a non-required block that failed while the stack continued."""
    acc["failed"], acc["error"] = True, err
    if brk or getattr(block, "block_id", "") in _OUTPUT_BLOCKS:
        acc["hard"] = True
        return brk
    acc["soft"].append(f"{_display(block)} ({err})")
    return False


def _soft_failures_forgiven(ctx: JobCtx, acc: Dict[str, Any]) -> bool:
    """B9 policy: optional (`required=False`) blocks that failed BEFORE the
    download do not fail a job whose image was then downloaded, validated
    and SAVED — the paid generation is on disk and the block rows already
    show the red status. Required breaks, VALIDATE/SAVE failures and
    cancellation keep their failure semantics (goldens req_fail / cancel)."""
    if not acc["failed"] or acc["hard"] or not acc["saved"] or not acc["soft"]:
        return False
    if _is_cancelled(ctx) or not _output_secured(ctx):
        return False
    _report_recovery(ctx, "⚠ Completed with warnings — the image was saved although "
                          "non-required block(s) failed: " + "; ".join(acc["soft"]), "warn")
    return True


def _absorb_block_result(ctx: JobCtx, block: Any, result: tuple, acc: Dict[str, Any]) -> bool:
    """Fold one block outcome into the run accumulator; True = stop the stack."""
    failed, err, brk = result
    if not failed:
        if getattr(block, "block_id", "") == "SAVE":
            acc["saved"] = True
        return False
    if _post_download_warning(ctx, block, err, acc["secured"]):
        return False
    return _record_failure(block, err, brk, acc)


async def _loop_blocks(ctx: JobCtx, blocks: List[Any]) -> tuple[bool, str]:
    acc: Dict[str, Any] = {"failed": False, "error": "", "hard": False, "soft": [],
                           "saved": False, "secured": False}
    for block in blocks:
        acc["secured"] = _output_secured(ctx)  # before the block runs (B8)
        result = await _run_one_checked(ctx, block)
        if _absorb_block_result(ctx, block, result, acc):
            break
        if _is_cancelled(ctx) and acc["failed"]:
            break
    if _soft_failures_forgiven(ctx, acc):
        return False, ""
    return acc["failed"], acc["error"]


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


async def run_blocks_for_image(ctx: JobCtx) -> tuple[bool, str, Optional[str], Optional[bytes]]:
    blocks = _get_blocks(ctx)
    _init_old_srcs(ctx)
    _reset_captcha_reports(ctx)
    failed, error = await _loop_blocks(ctx, blocks)
    _emit_captcha_job_lines(ctx, failed, error)
    return failed, error, ctx.new_src, ctx.file_bytes
