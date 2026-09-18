"""handle_captcha — the ONE choke point every captcha call site routes through.

Flow: visibility (existing predicate) → detect probe (kind + sitekey) →
stats → auto-solve (opt-in 2Captcha) → manual fallback (overlay + wait) →
cooldown penalty record (same choke point as the 2026-09-17 fix).

RULE 9 fail-open: probe errors, a missing service, or solver failures never
stall the job — they degrade to the manual flow. RULE 7: stop is honoured
inside the waits. Penalty records exactly once per solved edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.browser.captcha_probes import build_detect_js, build_hook_js

from .api_client import ApiError, Captcha2Client
from .key_store import CaptchaKeyStore, CaptchaSettings, clamp_timeout
from .signals import CaptchaSignal, SolveOutcome, host_of
from .solver import CaptchaSolver
from .stats import CaptchaStatsStore


@dataclass
class CaptchaCtx:
    """Per-call bundle (keeps handle_captcha + service methods ≤4 params)."""

    ctrl: Any
    pool: Any
    bridge: Any
    tab_id: str
    source: str = "job"
    stop: Optional[Callable[[], bool]] = None
    log: Optional[Callable[[str, str], None]] = None


def _log(ctx: CaptchaCtx, msg: str, level: str = "info") -> None:
    if ctx.log is not None:
        try:
            ctx.log(msg, level)
            return
        except Exception:
            pass
    try:
        ctx.bridge._log(msg, level)
    except Exception:
        pass


def _stop_pred(ctx: CaptchaCtx) -> Callable[[], bool]:
    return ctx.stop or (lambda: False)


def _service(ctx: CaptchaCtx) -> Optional["CaptchaService"]:
    fn = getattr(ctx.bridge, "_captcha_service", None)
    if fn is None:
        return None
    try:
        return fn()
    except Exception:
        return None


def _record_stats(ctx: CaptchaCtx, event: str, site: str = "") -> None:
    try:
        svc = _service(ctx)
        if svc is not None:
            svc.stats.record(event, site)
    except Exception:
        pass


def _record_penalty(ctx: CaptchaCtx) -> None:
    """Stack the cooldown penalty (never breaks the job on failure)."""
    try:
        from app.services.cooldown_service import note_captcha_event
        note_captcha_event(ctx.pool, ctx.tab_id, ctx.bridge, source=ctx.source)
    except Exception as e:
        _log(ctx, f"Captcha penalty skipped: {e}", "warn")


def _mark_waiting(ctx: CaptchaCtx) -> None:
    try:
        if ctx.pool is not None:
            ctx.pool.mark_waiting(ctx.tab_id, "captcha")
            ctx.bridge._emit_pool_status()
    except Exception:
        pass


def _page_url(ctx: CaptchaCtx) -> str:
    try:
        page = ctx.pool.get_page(ctx.tab_id) if ctx.pool is not None else None
        return getattr(page, "url", "") or ""
    except Exception:
        return ""


def _wait_timeout(ctx: CaptchaCtx) -> int:
    try:
        return int(ctx.bridge.config.get_state("watcher_captcha_timeout_sec", 300))
    except Exception:
        return 300


def _anchor_desc(signal: CaptchaSignal) -> str:
    """Anchor-src diagnostics for the detect log line (cb callable? sizes?)."""
    a = signal.anchor
    return (f"anchor cb={'yes' if a.get('cb') else 'no'} size={a.get('size') or '-'} "
            f"ams={a.get('ams') or '-'} ems={a.get('ems') or '-'}")


def _hook_desc(signal: CaptchaSignal) -> str:
    """Render-hook evidence: is the canonical solve path available (design §2.4)?"""
    h = signal.hook or {}
    if h.get("captured"):
        key = str(h.get("sitekey") or "-")[-6:]
        try:
            age = f"{float(h.get('ageSec', -1)):.0f}s"
        except Exception:
            age = "?"
        return f"hook=captured(sitekey=…{key}, age={age})"
    return "hook=ready" if h.get("ready") else "hook=absent"


async def detect_signal(ctx: CaptchaCtx) -> CaptchaSignal:
    """Kind + sitekey probe; probe error → probe_error (fail open, RULE 9)."""
    try:  # defense-in-depth: idempotent no-op when the attach install ran
        await ctx.ctrl.cdp.evaluate(build_hook_js())
    except Exception:
        pass
    try:
        res = await ctx.ctrl.cdp.evaluate(build_detect_js())
    except Exception as e:
        _log(ctx, f"Captcha detect probe failed: {e}", "warn")
        return CaptchaSignal(visible=True, kind="probe_error", page_url=_page_url(ctx))
    signal = CaptchaSignal.from_result(res)
    if not signal.page_url:
        signal.page_url = _page_url(ctx)
    return signal


async def handle_captcha(ctx: CaptchaCtx) -> SolveOutcome:
    """Detect → stats → auto-solve (opt-in) → manual wait → penalty record.

    Callers gate on `is_security_dialog_visible()` first; the detect probe's
    own visible flag covers the vanishing-dialog race (→ `none`, no penalty).
    The manual wait always states WHY the app is not solving (visual flag).
    """
    signal = await detect_signal(ctx)
    if not signal.visible:
        return SolveOutcome(status="none")
    _mark_waiting(ctx)
    _record_stats(ctx, "detected", host_of(signal.page_url))
    _log(ctx, f"🛡️ Captcha detected ({signal.kind}, sitekey={'set' if signal.sitekey else 'missing'}, "
              f"{_anchor_desc(signal)}, {_hook_desc(signal)}) via {ctx.source}", "error")
    svc = _service(ctx)
    if svc is not None and svc.auto_enabled() and signal.solvable:
        outcome = await _try_auto(ctx, signal, svc)
        if outcome.status == "solved":
            _record_penalty(ctx)
            return outcome
        return await _manual_wait(ctx, signal, f"auto-solve failed: {outcome.reason}")
    if svc is not None and svc.auto_enabled():
        _log(ctx, "⚠️ FLAG CAPTCHA_AUTO skipped — no sitekey in dialog — manual wait", "warn")
        return await _manual_wait(ctx, signal, "auto-solve: no sitekey in dialog")
    return await _manual_wait(ctx, signal, "auto-solve OFF — solve in Chrome (enable 2Captcha in the Captcha window)")


async def _try_auto(ctx: CaptchaCtx, signal: CaptchaSignal, svc: CaptchaService) -> SolveOutcome:
    """One 2Captcha attempt with its flag log; caller decides the fallback."""
    _log(ctx, f"🤖 FLAG CAPTCHA_AUTO — 2Captcha auto-solve started (tab {str(ctx.tab_id)[:12]})", "warn")
    outcome = await svc.solver.solve(ctx.ctrl, ctx.tab_id, signal, _stop_pred(ctx))
    if outcome.status != "solved":
        _log(ctx, f"2Captcha auto-solve failed ({outcome.reason}) — falling back to manual wait", "warn")
    return outcome


async def _manual_wait(ctx: CaptchaCtx, signal: CaptchaSignal, reason: str) -> SolveOutcome:
    """Overlay (with the why-not-solving flag) + poll until the dialog clears."""
    timeout = _wait_timeout(ctx)
    _log(ctx, f"🛡️ FLAG CAPTCHA_WAITING — captcha on screen (tab {str(ctx.tab_id)[:12]}, {host_of(signal.page_url)}) — awaiting your solve in Chrome", "error")
    try:
        await ctx.ctrl.show_watcher_overlay("wait for user. Captcha", kind="captcha",
                                            timeout_sec=timeout, sub=reason)
    except Exception:
        pass
    from app.services.cooldown_service import wait_captcha_cleared
    solved = await wait_captcha_cleared(ctx.ctrl, _stop_pred(ctx), timeout,
                                        lambda m, l="info": _log(ctx, m, l))
    try:
        await ctx.ctrl.hide_watcher_overlay()
    except Exception:
        pass
    if not solved:
        return SolveOutcome(status="stopped", reason="stop requested while waiting for solve")
    _record_stats(ctx, "manual_solved", host_of(signal.page_url))
    _record_penalty(ctx)
    return SolveOutcome(status="manual", method="manual")


class CaptchaService:
    """Bridge-side facade: key store + stats + solver + payloads (no Qt)."""

    def __init__(self, config_dir: str, log: Optional[Callable[[str, str], None]] = None):
        self.keys = CaptchaKeyStore(config_dir)
        self.stats = CaptchaStatsStore(config_dir)
        self._log = log or (lambda msg, level="info": None)
        self.solver = CaptchaSolver(self.keys, self.stats, self._log)

    def auto_enabled(self) -> bool:
        try:
            s = self.keys.load()
            return s.enabled and bool(s.api_key)
        except Exception:
            return False

    def apply_settings(self, api_key: str, enabled: bool, solve_timeout_sec: int) -> Dict[str, Any]:
        s = CaptchaSettings(enabled=bool(enabled and bool(api_key)),
                            api_key=(api_key or "").strip(),
                            solve_timeout_sec=clamp_timeout(solve_timeout_sec))
        self.keys.save(s)
        return {"ok": True, "enabled": s.enabled, "has_key": bool(s.api_key),
                "masked_key": CaptchaKeyStore.mask(s.api_key)}

    async def refresh_balance(self) -> Optional[float]:
        """One-shot balance fetch (fire-and-forget from slots); never raises."""
        s = self.keys.load()
        if not s.api_key:
            return None
        client = Captcha2Client(s.api_key)
        try:
            balance = await client.get_balance()
        except ApiError as e:
            self.stats.set_last_error(f"balance: {e.reason}")
            self._log(f"2Captcha balance check failed: {e.reason}", "warn")
            return None
        except Exception as e:
            self._log(f"2Captcha balance check error: {e}", "warn")
            return None
        finally:
            await client.aclose()
        self.stats.set_balance(balance)
        self._log(f"2Captcha balance ${balance:.2f}", "info")
        return balance

    def status_payload(self) -> Dict[str, Any]:
        s = self.keys.load()
        return {"enabled": s.enabled, "has_key": bool(s.api_key),
                "masked_key": CaptchaKeyStore.mask(s.api_key),
                "solve_timeout_sec": s.solve_timeout_sec,
                "balance": self.stats.last_balance, "balance_at": self.stats.balance_at,
                "last_error": self.stats.last_error}

    def stats_payload(self) -> Dict[str, Any]:
        return self.stats.to_dict()
