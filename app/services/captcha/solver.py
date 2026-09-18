"""CaptchaSolver — per-tab 2Captcha solving, non-blocking across pages.

* one inflight asyncio task per tab_id: two racing checks on the same page
  share one 2Captcha task (no double billing); different tabs solve in
  parallel (multi-tasking) — a solve on tab A never blocks tab B.
* never raises: every failure path returns a SolveOutcome with a reason
  (RULE 4) so the caller can fall back to the manual flow.
* stop honoured inside the poll loop (RULE 7); abandoned tasks are deleted
  to free credit.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

from app.browser.captcha_probes import build_continue_js, build_detect_js, build_inject_js
from app.utils.page_errors import match_page_error

from .api_client import ApiError, Captcha2Client, POLL_INTERVAL_SEC
from .signals import CaptchaSignal, SolveOutcome, host_of

VERIFY_GRACE_SEC = 20.0  # after injection: how long to watch the dialog close
HEARTBEAT_SEC = 30.0  # processing polls: log a still-waiting line this often
# Google tokens are single-use and expire ~2 min after issue (pass-path doc §3
# G4). Injection happens seconds after receipt today; the guard encodes the
# contract so a future slower path can never silently inject a dead token.
TOKEN_MAX_AGE_SEC = 100.0
MAX_TRANSIENT_POLL_ERRORS = 3  # tolerate short 2Captcha/HTTP response glitches

_TASK_TYPES = {
    "recaptcha_enterprise": "RecaptchaV2EnterpriseTaskProxyless",
    "recaptcha_v2": "RecaptchaV2TaskProxyless",
}


@dataclass
class SolvePlan:
    """Per-solve bundle to keep solver methods ≤4 params (RULE 16)."""

    client: Captcha2Client
    ctrl: Any
    tab_id: str
    signal: CaptchaSignal
    stop: Callable[[], bool]
    start: float
    task_id: str = ""  # provider task (traceability on failure paths, RULE 22)
    stats: Any = None
    logger: Optional[Callable[[str, str], None]] = None
    token_at: float = 0.0  # monotonic() when the provider token arrived
    err_base: Optional[str] = None  # error-scan corpus at solve start (None = not taken)
    err_seen: bool = False  # a mid-solve page error was already logged
    polls: int = 0  # provider poll rounds (report retry count)
    token_fp: str = ""  # token fingerprint (shape only)
    dialog_at_token: str = ""  # visible | gone | "" (no token yet)
    inject: str = ""  # "scope=.. fields=.. cb=.." summary
    page_error_at: float = 0.0  # solve-start-relative seconds of a mid-solve error
    page_error: str = ""
    stale_reason: str = ""
    page_identity: str = ""
    challenge_identity: str = ""


def _failed(reason: str, detail: str = "", plan: Optional[SolvePlan] = None) -> SolveOutcome:
    """Auto attempt failed — caller may fall back to manual (RULE 4)."""
    status = "page_error" if reason == "page_error" else "token_stale" if reason == "token_stale" else "auto_failed"
    out = SolveOutcome(status=status, reason=f"{reason}: {detail}".strip(": "), method="auto")
    if plan is not None:
        out.polls = plan.polls
        out.task_id = plan.task_id
        if plan.token_at:
            out.token_sec = plan.token_at - plan.start
            out.token_fp = plan.token_fp
        out.dialog_at_token = plan.dialog_at_token
        out.inject = plan.inject
        out.page_error_at_s = plan.page_error_at
        out.page_error = plan.page_error
    return out


def task_type_for(kind: str) -> str:
    return _TASK_TYPES.get(kind, "RecaptchaV2EnterpriseTaskProxyless")


def _cb_source(res: Dict[str, Any]) -> str:
    """Which chain step was attempted (tolerates legacy-shaped results)."""
    return str(res.get("cbSource") or res.get("cb") or "?")[:40]


def _cb_desc(res: Dict[str, Any]) -> str:
    """Inject-result callback status for the log line."""
    if res.get("cbCalled"):
        return f"called {res.get('cb')} via {_cb_source(res)}"
    if res.get("cbError"):
        return f"{_cb_source(res)} error: {str(res.get('cbError'))[:40]}"
    return "no site callback found (data-callback / grecaptcha cfg / anchor cb)"


def _reject_reason(res: Dict[str, Any]) -> str:
    """Not-accepted reason: was the widget callback invoked before expiry?"""
    if res.get("cbCalled"):
        return (f"dialog still visible after token injection (callback called via "
                f"{_cb_source(res)} — token likely rejected server-side)")
    return ("dialog still visible after token injection (no site callback found: "
            "data-callback / grecaptcha cfg / anchor cb)")


def _failed_detail(res: Dict[str, Any]) -> str:
    """Provider's own words for a failed task (errorCode preferred)."""
    return str(res.get("errorCode") or res.get("errorDescription") or "")


def _heartbeat(log: Callable[[str, str], None], plan: SolvePlan,
               task_id: str, last: float) -> float:
    """Still-processing line every HEARTBEAT_SEC; returns the new mark."""
    now = time.monotonic()
    if now - last < HEARTBEAT_SEC:
        return last
    log(f"🤖 2Captcha task #{task_id} still processing ({now - plan.start:.0f}s elapsed)", "info")
    return now


async def _note_page_error(plan: SolvePlan, log: Callable[[str, str], None]) -> bool:
    """Observe a new fatal page error; true means the solve is terminal."""
    if plan.page_error:
        return True
    scan = getattr(plan.ctrl, "scan_page_errors", None)
    if scan is None:
        return False
    try:
        corpus = await scan()
    except Exception:
        return False
    if plan.err_base is None:  # first call: baseline, never report
        plan.err_base = corpus if isinstance(corpus, str) else ""
        return False
    err = match_page_error(corpus if isinstance(corpus, str) else "", plan.err_base)
    if not err:
        return False
    plan.err_seen = True
    plan.page_error_at = time.monotonic() - plan.start
    plan.page_error = err
    log(f"🛡️ page error appeared during solve ({plan.page_error_at:.0f}s in): {err}", "warn")
    return True


def _stale_token_reason(plan: SolvePlan) -> str:
    """Non-empty when the token outlived Google's single-use window."""
    age = time.monotonic() - plan.token_at
    if age <= TOKEN_MAX_AGE_SEC:
        return ""
    return f"token age {age:.0f}s exceeds Google's ~2-minute single-use window"


def _note_escalation(signal: Any, log: Callable[[str, str], None]) -> None:
    """Report-only: bframe image-grid escalation visible at solve start."""
    if getattr(signal, "challenge_active", False):
        log("🖼️ image-challenge escalation visible (bframe) — the provider "
            "solves the selection on its side; expect a longer solve", "info")


def _token_fingerprint(token: str) -> str:
    """Token evidence for logs: shape only, never the token (RULE 20)."""
    t = str(token or "")
    if not t:
        return "EMPTY"
    if len(t) <= 16:
        return f"SUSPICIOUS len={len(t)}"
    return f"len={len(t)} head={t[:8]} tail={t[-4:]}"


def _task_payload(task_type: str, signal: CaptchaSignal) -> Dict[str, Any]:
    """Docs-exact createTask payload (2captcha.com/api-docs/recaptcha-v2-enterprise)."""
    payload = {"type": task_type,
               "websiteURL": signal.page_url,
               "websiteKey": signal.sitekey}
    if task_type.startswith("RecaptchaV2Enterprise"):
        payload["isInvisible"] = signal.is_invisible  # true = no visible checkbox
    return payload



async def _delete_task(client: Captcha2Client, task_id: str, stats: Any,
                     log: Callable[[str, str], None]) -> None:
    """Free credit on an abandoned task; best effort, never raises."""
    try:
        if await client.delete_task(task_id):
            stats.record("task_deleted")
            log(f"🤖 2Captcha task #{task_id} deleted (credit freed)", "info")
    except Exception:
        pass


async def _click_continue(ctrl: Any) -> None:
    """Best effort: the site may auto-submit on token receipt instead."""
    try:
        await ctrl.cdp.evaluate(build_continue_js())
    except Exception:
        pass


async def _note_preinject_state(plan: SolvePlan, log: Callable[[str, str], None]) -> None:
    """Log + stamp whether the dialog is still up when the token arrives."""
    try:
        visible = await plan.ctrl.is_security_dialog_visible()
    except Exception:
        return
    plan.dialog_at_token = "visible" if visible else "gone"
    log("🤖 token arrived, dialog still visible — injecting" if visible else
        "🤖 token arrived but the dialog is already gone (page moved on?) — injecting anyway",
        "info")


async def _verify_gone(ctrl: Any, stop: Callable[[], bool]) -> bool:
    """Watch the dialog close after injection; fail closed on probe error."""
    deadline = time.monotonic() + VERIFY_GRACE_SEC
    while time.monotonic() < deadline:
        if stop():
            return False
        try:
            if not await ctrl.is_security_dialog_visible():
                return True
        except Exception:
            pass
        await asyncio.sleep(2.0)
    try:
        return not await ctrl.is_security_dialog_visible()
    except Exception:
        return False


async def _current_signal(ctrl: Any) -> Optional[CaptchaSignal]:
    """Read fresh page identity/evidence before using a provider token."""
    try:
        raw = await ctrl.cdp.evaluate(build_detect_js())
        return CaptchaSignal.from_result(raw)
    except Exception:
        return None


def _identity_reason(plan: SolvePlan, current: CaptchaSignal) -> str:
    """Compare stable page/challenge evidence."""
    if plan.page_identity and current.page_identity and plan.page_identity != current.page_identity:
        return "page_identity_changed"
    if plan.challenge_identity and current.challenge_identity and plan.challenge_identity != current.challenge_identity:
        return "challenge_identity_changed"
    return ""


def _sitekey_changed(plan: SolvePlan, current: CaptchaSignal) -> bool:
    """Only compare sitekeys when the fresh probe has identity evidence."""
    return bool(plan.signal.sitekey and current.sitekey
                and (current.page_identity or current.challenge_identity)
                and plan.signal.sitekey != current.sitekey)


async def _stale_reason(plan: SolvePlan) -> str:
    """Return a mismatch reason; empty means the page is still the same."""
    current = await _current_signal(plan.ctrl)
    if current is None:
        return ""
    return _identity_reason(plan, current) or ("sitekey_changed" if _sitekey_changed(plan, current) else "")


async def _inject_failure(plan: SolvePlan, task_id: str) -> SolveOutcome:
    """Record missing response fields and release the provider task."""
    await _delete_task(plan.client, task_id, plan.stats, plan.logger)
    _auto_fail(plan, "inject", "response field not found on page")
    return _failed("inject", "response field not found on page", plan)


async def _page_error_outcome(plan: SolvePlan, task_id: str,
                              stats: Any, log: Callable[[str, str], None]) -> Optional[SolveOutcome]:
    """Return terminal page-error outcome and free the provider task."""
    if not await _note_page_error(plan, log):
        return None
    await _delete_task(plan.client, task_id, stats, log)
    return _failed("page_error", plan.page_error, plan)


async def _inject(ctrl: Any, token: str, sitekey: str,
                 log: Callable[[str, str], None]) -> Dict[str, Any]:
    """Set response fields and invoke the page callback; never raises."""
    try:
        res = await ctrl.cdp.evaluate(build_inject_js(token, sitekey))
    except Exception as e:
        log(f"2Captcha inject probe failed: {e}", "warn")
        return {}
    try:
        data = json.loads(res) if isinstance(res, str) else res
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _auto_fail(plan: SolvePlan, reason: str, detail: str) -> None:
    """Record a provider attempt failure without growing CaptchaSolver."""
    try:
        plan.stats.record("auto_failed", host_of(plan.signal.page_url))
        plan.stats.set_last_error(detail[:80])
        plan.logger(f"🤖 2Captcha auto-solve failed: {reason}", "warn")
    except Exception:
        pass


async def _stale_outcome(plan: SolvePlan, task_id: str, stats: Any,
                          log: Callable[[str, str], None]) -> Optional[SolveOutcome]:
    """Delete provider work and return `token_stale` when the token is unusable.

    Two independent guards, cheapest first: the token's own age (Google's
    single-use ~2-minute window, pass-path round) and the page/challenge
    identity it was requested for (token-vs-page round). Either one means the
    token must never be injected.
    """
    reason = _stale_token_reason(plan) or await _stale_reason(plan)
    if not reason:
        return None
    plan.stale_reason = reason
    log(f"🤖 token refused before injection — {reason}", "warn")
    await _delete_task(plan.client, task_id, stats, log)
    return _failed("token_stale", reason, plan)


def _poll_fail(plan: SolvePlan, why: str, detail: str = "") -> Tuple[None, str]:
    plan.stats.record("auto_failed", host_of(plan.signal.page_url))
    plan.stats.set_last_error(detail or why)
    suffix = f" ({detail})" if detail and detail != why else ""
    plan.logger(f"2Captcha poll ended: {why}{suffix}", "warn")
    return None, why


async def _retry_network(plan: SolvePlan, started: float, count: int,
                         timeout_sec: int) -> bool:
    """Wait before another transient poll; false means retry budget expired."""
    elapsed = time.monotonic() - started
    if count >= MAX_TRANSIENT_POLL_ERRORS or elapsed > timeout_sec:
        return False
    plan.logger(
        f"2Captcha poll network glitch — retrying "
        f"({count}/{MAX_TRANSIENT_POLL_ERRORS}, {elapsed:.0f}s elapsed)", "warn")
    await asyncio.sleep(POLL_INTERVAL_SEC)
    return True


async def _provider_result(plan: SolvePlan, res: Dict[str, Any]
                           ) -> Tuple[bool, Optional[str], str]:
    """Interpret one successful provider response."""
    if await _note_page_error(plan, plan.logger):
        return True, None, "page_error"
    status = res.get("status")
    if status == "ready":
        token = str((res.get("solution") or {}).get("gRecaptchaResponse") or "")
        return True, token, ""
    if status == "failed":
        token, why = _poll_fail(plan, "task_failed", _failed_detail(res))
        return True, token, why
    return False, None, ""


async def _poll_task(plan: SolvePlan, task_id: str,
                     timeout_sec: int) -> Tuple[Optional[str], str]:
    """Poll until a token arrives; (None, why) on stop/error/timeout."""
    start = time.monotonic()
    last_beat = start
    transient_errors = 0
    while True:
        if plan.stop():
            plan.logger("2Captcha polling stopped (user stop)", "info")
            return None, "stopped"
        plan.polls += 1
        try:
            res = await plan.client.get_result(task_id)
        except ApiError as exc:
            transient_errors += 1
            if exc.reason == "network" and await _retry_network(
                    plan, start, transient_errors, timeout_sec):
                continue
            return _poll_fail(plan, exc.reason, str(exc))
        transient_errors = 0
        done, token, why = await _provider_result(plan, res)
        if done:
            return token, why
        if time.monotonic() - start > timeout_sec:
            return _poll_fail(plan, "poll_timeout")
        last_beat = _heartbeat(plan.logger, plan, task_id, last_beat)
        await asyncio.sleep(POLL_INTERVAL_SEC)


def _solved(plan: SolvePlan, task_id: str) -> SolveOutcome:
    secs = time.monotonic() - plan.start
    tok = plan.token_at - plan.start if plan.token_at else 0.0
    plan.stats.record("auto_solved", host_of(plan.signal.page_url))
    plan.logger(f"🤖 2Captcha solved tab {str(plan.tab_id)[:12]} in {secs:.0f}s "
                f"(token {tok:.0f}s, token accepted)", "success")
    return SolveOutcome(status="solved", method="auto", task_id=task_id,
                        reason="token accepted", elapsed_sec=secs,
                        polls=plan.polls, token_sec=tok, token_fp=plan.token_fp,
                        dialog_at_token=plan.dialog_at_token, inject=plan.inject,
                        page_error_at_s=plan.page_error_at, page_error=plan.page_error)


async def _accepted_after_close(plan: SolvePlan, task_id: str) -> SolveOutcome:
    """Check for a concurrent page failure, then accept the dialog closure."""
    error = await _page_error_outcome(plan, task_id, plan.stats, plan.logger)
    if error is not None:
        return error
    # The accepted-token transition can expose a badge with a different key.
    # Staleness was checked immediately before injection, so do not mistake
    # this expected post-close transition for `token_stale: sitekey_changed`.
    return _solved(plan, task_id)


class CaptchaSolver:
    """Owns the inflight task map; all methods are small (RULE 18)."""

    def __init__(self, keys: Any, stats: Any, log: Callable[[str, str], None]):
        self._keys = keys
        self._stats = stats
        self._log = log
        self._inflight: Dict[str, asyncio.Task] = {}

    async def solve(self, ctrl: Any, tab_id: str, signal: CaptchaSignal,
                    stop: Optional[Callable[[], bool]] = None) -> SolveOutcome:
        """Deduped per-tab entry: concurrent callers share one solve."""
        inflight = self._inflight.get(tab_id)
        if inflight is not None and not inflight.done():
            return await inflight
        task = asyncio.create_task(self._solve_once(ctrl, tab_id, signal, stop or (lambda: False)))
        self._inflight[tab_id] = task
        try:
            return await task
        finally:
            self._inflight.pop(tab_id, None)

    async def _solve_once(self, ctrl: Any, tab_id: str, signal: CaptchaSignal,
                          stop: Callable[[], bool]) -> SolveOutcome:
        settings = self._keys.load()
        if not settings.api_key:
            return _failed("no_key", "no 2Captcha key stored")
        self._stats.record("task_created", host_of(signal.page_url))
        client = Captcha2Client(settings.api_key)
        try:
            plan = SolvePlan(client=client, ctrl=ctrl, tab_id=tab_id, signal=signal,
                             stop=stop, start=time.monotonic(), stats=self._stats,
                             logger=self._log,
                             page_identity=signal.page_identity,
                             challenge_identity=signal.challenge_identity)
            return await self._run_task(plan, settings.solve_timeout_sec)
        finally:
            await client.aclose()

    async def _run_task(self, plan: SolvePlan, timeout_sec: int) -> SolveOutcome:
        _note_escalation(plan.signal, self._log)
        task_id = await self._create_task(plan)
        if not task_id:
            return _failed("task_create", "createTask failed", plan)
        plan.task_id = task_id  # traceability on poll-failure paths (RULE 22)
        token, why = await _poll_task(plan, task_id, timeout_sec)
        if not token:
            await _delete_task(plan.client, task_id, self._stats, self._log)
            return _failed(why or "no_token", "no solution token", plan)
        plan.token_at = time.monotonic()
        plan.token_fp = _token_fingerprint(token)
        self._log(f"🤖 2Captcha task #{task_id} token received in "
                  f"{plan.token_at - plan.start:.0f}s ({plan.token_fp})", "success")
        return await self._inject_and_verify(plan, token, task_id)

    async def _inject_and_verify(self, plan: SolvePlan, token: str, task_id: str) -> SolveOutcome:
        stale = await _stale_outcome(plan, task_id, self._stats, self._log)
        if stale is not None:
            return stale
        error = await _page_error_outcome(plan, task_id, self._stats, self._log)
        if error is not None:
            return error
        await _note_preinject_state(plan, self._log)
        if plan.dialog_at_token == "gone":
            await _delete_task(plan.client, task_id, self._stats, self._log)
            return _failed("token_stale", "dialog_gone_before_token_injection", plan)
        res = await _inject(plan.ctrl, token, plan.signal.sitekey, self._log)
        if not res.get("ok"):
            return await _inject_failure(plan, task_id)
        plan.inject = f"scope={res.get('scope')} fields={res.get('fields', 1)} cb={_cb_desc(res)}"
        self._log(f"🤖 token injected ({plan.inject})", "info")
        await _click_continue(plan.ctrl)
        error = await _page_error_outcome(plan, task_id, self._stats, self._log)
        if error is not None:
            return error
        if await _verify_gone(plan.ctrl, plan.stop):
            return await _accepted_after_close(plan, task_id)
        await _delete_task(plan.client, task_id, self._stats, self._log)
        why = _reject_reason(res)
        _auto_fail(plan, "not_accepted", why)
        return _failed("not_accepted", why, plan)

    async def _create_task(self, plan: SolvePlan) -> str:
        task_type = task_type_for(plan.signal.kind)
        payload = _task_payload(task_type, plan.signal)
        try:
            task_id = await plan.client.create_task(payload)
            self._log(f"🤖 2Captcha task {task_type} #{task_id} submitted (tab {str(plan.tab_id)[:12]}, "
                      f"isInvisible={plan.signal.is_invisible}, key=****)", "info")
            return task_id
        except ApiError as e:
            self._stats.record("auto_failed", host_of(plan.signal.page_url))
            self._stats.set_last_error(e.reason)
            self._log(f"🤖 2Captcha createTask failed: {e.reason}", "warn")
            return ""
        except Exception as e:  # fail-open: solver problems never kill the job
            self._log(f"2Captcha createTask unexpected error: {e}", "warn")
            return ""

