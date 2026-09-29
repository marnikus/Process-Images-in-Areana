from __future__ import annotations
from typing import Any
from .context import JobCtx, log
from .emit import _emit_action, _mark_waiting, _mark_busy
from .state import _tab_aborted
from app.services.captcha.policy import captcha_in_scope

_CAPTCHA_FAILURES = {
    "stopped": lambda o: "Cancelled during CAPTCHA",
    "page_error": lambda o: o.reason or "Page error during CAPTCHA",
    "wait_timeout": lambda o: o.reason or "Captcha wait exceeded its cap",  # S3: cooldown still applies
}

def _handle_captcha_outcome(ctx: JobCtx, outcome: Any) -> None:
    """Map security outcomes without mistaking manual supersession for failure."""
    fail = _CAPTCHA_FAILURES.get(outcome.status)
    if fail is not None:
        raise RuntimeError(fail(outcome))
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
    """Captcha gate (RULE 20): in scope only while the Watcher is ON, then detect + wait."""
    if not captcha_in_scope(ctx.bridge):
        return False  # RULE 9: "no captcha", the stack continues
    try:
        visible = await ctx.ctrl.is_security_dialog_visible()
    except Exception:
        visible = False
    if not visible:
        return False
    await _run_security_captcha(ctx)
    return True

async def _handle_security(ctx: JobCtx, block: Any):
    """Handle security (announce while waiting, like the legacy loop); OFF ⇒ skipped, no probe."""
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

