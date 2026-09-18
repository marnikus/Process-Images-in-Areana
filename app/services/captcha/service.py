"""handle_captcha — the ONE choke point every captcha call site routes through.

Flow: visibility (existing predicate) → detect probe (kind + sitekey) →
stats → auto-solve (opt-in 2Captcha) → manual fallback (overlay + wait) →
cooldown penalty record (same choke point as the 2026-09-17 fix).

RULE 9 fail-open: probe errors, a missing service, or solver failures never
stall the job — they degrade to the manual flow. RULE 7: stop is honoured
inside the waits. Penalty records exactly once per solved edge.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.browser.captcha_probes import build_detect_js
from app.core.cooldown import DEFAULT_PENALTY_SECONDS
from app.services.captcha_recording import RecordingManager

from .api_client import POLL_INTERVAL_SEC, ApiError, Captcha2Client
from .key_store import CaptchaKeyStore, CaptchaSettings, clamp_timeout
from .signals import CaptchaSignal, SolveOutcome, host_of
from .solver import CaptchaSolver, task_type_for
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


def _signal_evidence(signal: CaptchaSignal) -> Dict[str, Any]:
    """Report-only page evidence; never includes token material."""
    return {
        "integration": signal.integration,
        "anchor": {"present": signal.anchor_present, "visible": signal.anchor_visible},
        "challenge": {"present": signal.challenge_present, "visible": signal.challenge_visible,
                       "title": signal.challenge_title, "src": signal.challenge_src,
                       "identity": signal.challenge_identity},
        "response_fields": {"count": signal.response_fields, "scope": signal.response_scope},
        "sitekey_source": signal.sitekey_source,
        "page_identity": signal.page_identity,
        "callback": {"attempted": False, "source": "", "called": False},
        "acceptance": {"state": "pending", "at_s": 0.0},
        "stale": None,
    }


def _new_encounter(ctx: CaptchaCtx, signal: CaptchaSignal) -> Dict[str, Any]:
    """Fresh report skeleton, stamped at detection (attempt fields blank)."""
    report = {
        "v": 1, "eid": uuid.uuid4().hex[:8], "tab": ctx.tab_id, "source": ctx.source,
        "kind": signal.kind, "url": signal.page_url, "dom": signal.dom,
        "sitekey": signal.sitekey, "invisible": signal.is_invisible,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "detect_to_solve_s": 0.0, "task_type": "", "task_id": "", "polls": 0,
        "attempts": 1,
        "poll_interval_s": POLL_INTERVAL_SEC, "token": None, "dialog_at_token": "",
        "inject": "", "page_error": None, "status": "", "reason": "", "method": "",
        "penalty_s": 0, "solve_total_s": 0.0, "_detected_mono": time.monotonic(),
    }
    report.update(_signal_evidence(signal))
    return report


def _finish_auto(rep: Dict[str, Any], outcome: SolveOutcome,
                 solve_mono: float, task_type: str) -> None:
    """Fill the 2Captcha-attempt fields (durations relative to detect)."""
    det = rep.get("_detected_mono", solve_mono)
    to_solve = round(solve_mono - det, 1)
    rep["detect_to_solve_s"] = to_solve
    rep["task_type"] = task_type
    rep["task_id"] = outcome.task_id
    rep["polls"] = outcome.polls
    rep["attempts"] = outcome.attempts
    rep["token"] = ({"at_s": round(to_solve + outcome.token_sec, 1),
                     "fp": outcome.token_fp} if outcome.token_fp else None)
    rep["dialog_at_token"] = outcome.dialog_at_token
    rep["inject"] = outcome.inject
    rep["callback"] = {"attempted": bool(outcome.inject),
                       "source": outcome.inject.split(" via ", 1)[1].split(")", 1)[0]
                       if " via " in outcome.inject else "",
                       "called": "cb=called" in outcome.inject}
    acceptance_at = outcome.page_error_at_s if outcome.status == "page_error" else outcome.token_sec
    rep["acceptance"] = {"state": outcome.status, "at_s": round(to_solve + acceptance_at, 1)}
    rep["page_error"] = ({"at_s": round(to_solve + outcome.page_error_at_s, 1),
                          "text": outcome.page_error} if outcome.page_error else None)
    if outcome.status == "token_stale" or "stale" in outcome.reason:
        rep["stale"] = {"reason": outcome.reason, "at_s": round(to_solve + outcome.token_sec, 1)}


def _finish_resolution(rep: Dict[str, Any], outcome: SolveOutcome) -> None:
    """Fill status/reason/total (mutates rep, drops the internal stamp)."""
    det = rep.pop("_detected_mono", None)
    rep["status"] = outcome.status
    rep["reason"] = outcome.reason
    rep["method"] = outcome.method
    rep["solve_total_s"] = round(time.monotonic() - det, 1) if det else 0.0


def _penalty_seconds(ctx: CaptchaCtx) -> int:
    """Configured per-captcha penalty (fail-open to the default)."""
    try:
        return int(ctx.bridge.config.get_state("cooldown_captcha_penalty_seconds",
                                               DEFAULT_PENALTY_SECONDS))
    except Exception:
        return DEFAULT_PENALTY_SECONDS


def _stash_encounter(ctx: CaptchaCtx, eid: str) -> None:
    """Remember the eid on the ctrl for the runner's CAPTCHA_JOB line."""
    if not eid:
        return
    try:
        lst = getattr(ctx.ctrl, "_captcha_reports", None)
        if not isinstance(lst, list):
            lst = []
            ctx.ctrl._captcha_reports = lst
        lst.append({"eid": eid, "tab": ctx.tab_id})
    except Exception:
        pass


def _emit_report(ctx: CaptchaCtx, rep: Dict[str, Any]) -> None:
    """Log the encounter JSON + stash the eid for the job-end join."""
    try:
        rep["penalty_s"] = _penalty_seconds(ctx) if rep.get("status") in ("solved", "manual") else 0
        _log(ctx, f"🧾 CAPTCHA_SOLVE {json.dumps(rep, ensure_ascii=False)}", "info")
    except Exception:
        pass
    _stash_encounter(ctx, str(rep.get("eid", "")))


def _wait_timeout(ctx: CaptchaCtx) -> int:
    try:
        return int(ctx.bridge.config.get_state("watcher_captcha_timeout_sec", 300))
    except Exception:
        return 300


async def detect_signal(ctx: CaptchaCtx) -> CaptchaSignal:
    """Kind + sitekey probe; probe error → probe_error (fail open, RULE 9)."""
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
    """Detect, record, resolve, and close one visible captcha encounter."""
    signal = await detect_signal(ctx)
    if not signal.visible:
        return SolveOutcome(status="none")
    rep = _new_encounter(ctx, signal)
    _mark_waiting(ctx)
    _record_stats(ctx, "detected", host_of(signal.page_url))
    _log(ctx, f"🛡️ Captcha detected ({signal.kind}, sitekey={'set' if signal.sitekey else 'missing'}) via {ctx.source}", "error")
    svc = _service(ctx)
    recorder = await svc.recordings.start(ctx.ctrl, rep) if svc is not None else None
    try:
        outcome = await _resolve_captcha(ctx, signal, svc, rep)
    except BaseException as exc:
        if svc is not None:
            await svc.recordings.abort(recorder, f"{type(exc).__name__}: {exc}")
        raise
    if svc is not None:
        await svc.recordings.finish(recorder, outcome)
    return outcome


async def _dialog_still_visible(ctx: CaptchaCtx) -> bool:
    """H4: can a human still solve this challenge right now? (fail closed)."""
    try:
        return bool(await ctx.ctrl.is_security_dialog_visible())
    except Exception:
        return False


async def _resolve_captcha(ctx: CaptchaCtx, signal: CaptchaSignal,
                           svc: Optional["CaptchaService"], rep: Dict[str, Any]) -> SolveOutcome:
    """Choose automatic or manual policy while recording stays orthogonal."""
    if svc is not None and svc.auto_enabled() and signal.solvable:
        outcome = await _try_auto(ctx, signal, svc, rep)
        await svc.recordings.note(ctx.tab_id, "auto_attempt_finished", outcome)
        if outcome.status == "solved":
            _record_penalty(ctx)
            return outcome
        if outcome.status == "page_error":
            return outcome
        if outcome.status == "token_stale" and not await _dialog_still_visible(ctx):
            _log(ctx, "challenge dialog already cleared — token_stale stands, no manual wait", "info")
            return outcome
        return await _manual_wait(ctx, signal, f"auto-solve failed: {outcome.reason}", rep)
    if svc is not None and svc.auto_enabled():
        _log(ctx, "⚠️ FLAG CAPTCHA_AUTO skipped — no sitekey in dialog — manual wait", "warn")
        return await _manual_wait(ctx, signal, "auto-solve: no sitekey in dialog", rep)
    reason = "auto-solve OFF — solve in Chrome (enable 2Captcha in the Captcha window)"
    return await _manual_wait(ctx, signal, reason, rep)


async def _try_auto(ctx: CaptchaCtx, signal: CaptchaSignal, svc: CaptchaService,
                 rep: Dict[str, Any]) -> SolveOutcome:
    """One 2Captcha attempt; fills + emits the report when solved."""
    _log(ctx, f"🤖 FLAG CAPTCHA_AUTO — 2Captcha auto-solve started (tab {str(ctx.tab_id)[:12]})", "warn")
    solve_mono = time.monotonic()
    outcome = await svc.solver.solve(ctx.ctrl, ctx.tab_id, signal, _stop_pred(ctx))
    _finish_auto(rep, outcome, solve_mono, task_type_for(signal.kind))
    if outcome.status != "solved":
        _finish_resolution(rep, outcome)
        _emit_report(ctx, rep)
        _log(ctx, f"2Captcha auto-solve failed ({outcome.reason}) — "
                  f"{'preserving page failure' if outcome.status == 'page_error' else 'falling back to manual wait'}", "warn")
        return outcome
    _finish_resolution(rep, outcome)
    _emit_report(ctx, rep)
    return outcome


async def _manual_wait(ctx: CaptchaCtx, signal: CaptchaSignal, reason: str,
                       rep: Dict[str, Any]) -> SolveOutcome:
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
        out = SolveOutcome(status="stopped", reason="stop requested while waiting for solve")
    else:
        _record_stats(ctx, "manual_solved", host_of(signal.page_url))
        _record_penalty(ctx)
        out = SolveOutcome(status="manual", method="manual")
    _finish_resolution(rep, out)
    _emit_report(ctx, rep)
    return out


class CaptchaService:
    """Bridge-side facade: key store + stats + solver + payloads (no Qt)."""

    def __init__(self, config_dir: str, log: Optional[Callable[[str, str], None]] = None):
        self.keys = CaptchaKeyStore(config_dir)
        self.stats = CaptchaStatsStore(config_dir)
        self._log = log or (lambda msg, level="info": None)
        self.solver = CaptchaSolver(self.keys, self.stats, self._log)
        self.recordings = RecordingManager(config_dir, self._log)

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
