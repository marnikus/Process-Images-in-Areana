"""handle_captcha — the ONE choke point every pipeline captcha call routes through.

Flow: visibility (existing predicate) → detect probe (kind + sitekey) →
stats → wait for the dialog to clear (overlay + poll) → cooldown penalty
record (same choke point as the 2026-09-17 fix).

The pipeline NEVER solves (2026-10-02 isolation): while this wait runs the
dialog is cleared either by the user in Chrome or by the Captcha Watcher
(`app.services.captcha_watcher`, the app's only solver) when it is ON.
The job simply resumes once the challenge is gone.

RULE 9 fail-open: probe errors or a missing service never stall the job —
they degrade to the plain wait. RULE 7: stop is honoured inside the wait.
Penalty records exactly once per cleared edge.
"""
# ideal-size(reason): one choke point whose phases (probe, stats, wait,
# penalty) must stay in one readable control flow — the phase helpers are
# separate functions, the sequence is not.

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.browser.captcha_probes import build_detect_js
from app.core.cooldown import DEFAULT_PENALTY_SECONDS
from app.services.captcha_recording import RecordingManager

from .key_store import CaptchaKeyStore, clamp_timeout
from .policy import captcha_in_scope, out_of_scope, solver_running
from .signals import CaptchaSignal, SolveOutcome, host_of
from .stats import CaptchaStatsStore

POLL_INTERVAL_SEC = 0.0  # report-schema compat: the pipeline no longer polls a solver


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
    if not captcha_in_scope(ctx.bridge):
        return out_of_scope()
    return await _handle_captcha_scoped(ctx)


async def _handle_captcha_scoped(ctx: CaptchaCtx) -> SolveOutcome:
    """Watcher-ON encounter: detect probe → stats → wait → record."""
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
        await svc.recordings.finish(recorder, outcome, rep)
    return outcome


async def _resolve_captcha(ctx: CaptchaCtx, signal: CaptchaSignal,
                           svc: Optional["CaptchaService"], rep: Dict[str, Any]) -> SolveOutcome:
    """Wait-only policy: the pipeline never solves; the Watcher (when ON) or
    the user clears the dialog. `svc` is kept for the call contract (stats)."""
    watcher_on = _watcher_running(ctx)
    reason = ("Captcha Watcher is solving it (2Captcha SDK)" if watcher_on
              else "solve in Chrome — or turn the Watcher ON to auto-solve")
    return await _manual_wait(ctx, signal, reason, rep)


def _watcher_running(ctx: CaptchaCtx) -> bool:
    """One owner for this question: `captcha.policy` (fail closed)."""
    return solver_running(ctx.bridge)


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
        method = "watcher" if _watcher_running(ctx) else "manual"
        out = SolveOutcome(status="manual", method=method)
    _finish_resolution(rep, out)
    _emit_report(ctx, rep)
    return out


class CaptchaService:
    """Bridge-side facade: key store + stats + recordings (no solver, no Qt).

    Solving moved to `app.services.captcha_watcher` (2026-10-02); this
    service only observes encounters for the pipeline's wait/penalty flow.
    """

    def __init__(self, config_dir: str, log: Optional[Callable[[str, str], None]] = None):
        self.keys = CaptchaKeyStore(config_dir)
        self.stats = CaptchaStatsStore(config_dir)
        self._log = log or (lambda msg, level="info": None)
        self.recordings = RecordingManager(config_dir, self._log)

    def apply_settings(self, api_key: str, solve_timeout_sec: int) -> Dict[str, Any]:
        """Persist the ACTIVE provider's key + timeout; `enabled` is always False
        (pipeline never solves). Other providers' keys are kept (B10)."""
        current = self.keys.load()
        s = current.with_key(current.provider, (api_key or "").strip())
        s.enabled = False
        s.solve_timeout_sec = clamp_timeout(solve_timeout_sec)
        self.keys.save(s)
        return {"ok": True, "enabled": False, "has_key": bool(s.api_key),
                "masked_key": CaptchaKeyStore.mask(s.api_key), "provider": s.provider}

    def status_payload(self) -> Dict[str, Any]:
        s = self.keys.load()
        return {"enabled": False, "has_key": bool(s.api_key),
                "masked_key": CaptchaKeyStore.mask(s.api_key), "provider": s.provider,
                "solve_timeout_sec": s.solve_timeout_sec,
                "balance": self.stats.last_balance, "balance_at": self.stats.balance_at,
                "last_error": self.stats.last_error}

    def stats_payload(self) -> Dict[str, Any]:
        return self.stats.to_dict()
