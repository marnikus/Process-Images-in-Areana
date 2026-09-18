"""CaptchaSolver — per-tab 2Captcha solving, non-blocking across pages.

* one inflight asyncio task per tab_id: two racing checks on the same page
  share one 2Captcha task (no double billing); different tabs solve in
  parallel (multi-tasking) — a solve on tab A never blocks tab B.
* never raises: every failure path returns a SolveOutcome with a reason
  (RULE 4) so the caller can fall back to the manual flow.
* stop honoured inside the poll loop (RULE 7); abandoned tasks are deleted
  to free credit.
* warm-up: a pre-started provider task (see warm.py) is consumed by the
  next solve, saving the createTask roundtrip; unconsumed warm tasks are
  deleted by the service's finally block.

Split by responsibility (RULE 18.2): polling.py owns "wait for the
provider", warm.py owns "pre-started tasks", plan.py owns the data bundle.
This file owns token application: staleness, injection, verification.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from app.browser.captcha_probes import build_continue_js, build_detect_js, build_inject_js

from .api_client import ApiError, Captcha2Client
from .plan import SolvePlan  # re-exported: solver stages + external readers
from .polling import note_page_error, poll_task
from .signals import CaptchaSignal, SolveOutcome, host_of
from .warm import WarmTaskPool, task_payload, task_type_for  # noqa: F401 (re-export)

VERIFY_GRACE_SEC = 20.0  # after injection: how long to watch the dialog close
# ideal-size: ~370 lines reason=token-application lifecycle (stale/inject/verify
# helpers) is one provider contract; poll/warm halves already extracted.


@dataclass
class SolveRequest:
    """One solve request bundle (RULE 16 params gate; RULE 19 parameter object)."""

    ctrl: Any
    tab_id: str
    signal: CaptchaSignal
    stop: Optional[Callable[[], bool]] = None
    timeout: Optional[float] = None  # None → key-store solve_timeout_sec


def _failed(reason: str, detail: str = "", plan: Optional[SolvePlan] = None) -> SolveOutcome:
    """Auto attempt failed — caller may fall back to manual (RULE 4)."""
    status = "page_error" if reason == "page_error" else "token_stale" if reason == "token_stale" else "auto_failed"
    out = SolveOutcome(status=status, reason=f"{reason}: {detail}".strip(": "), method="auto")
    if plan is not None:
        out.polls = plan.polls
        if plan.token_at:
            out.token_sec = plan.token_at - plan.start
            out.token_fp = plan.token_fp
        out.dialog_at_token = plan.dialog_at_token
        out.inject = plan.inject
        out.page_error_at_s = plan.page_error_at
        out.page_error = plan.page_error
    return out


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


def _token_fingerprint(token: str) -> str:
    """Token evidence for logs: shape only, never the token (RULE 20)."""
    t = str(token or "")
    if not t:
        return "EMPTY"
    if len(t) <= 16:
        return f"SUSPICIOUS len={len(t)}"
    return f"len={len(t)} head={t[:8]} tail={t[-4:]}"


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
    if not await note_page_error(plan, log):
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
    """Delete provider work and return an outcome when page evidence changed."""
    reason = await _stale_reason(plan)
    if not reason:
        return None
    plan.stale_reason = reason
    await _delete_task(plan.client, task_id, stats, log)
    return _failed("token_stale", reason, plan)


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
    """Owns the inflight task map + warm pool; all methods are small (RULE 18)."""

    def __init__(self, keys: Any, stats: Any, log: Callable[[str, str], None]):
        self._keys = keys
        self._stats = stats
        self._log = log
        self._inflight: Dict[str, asyncio.Task] = {}
        self._warm = WarmTaskPool(keys, stats, log, client_factory=Captcha2Client)

    def warm_up(self, tab_id: str, signal: CaptchaSignal) -> bool:
        """Pre-start the provider task so its latency overlaps the flow setup."""
        return self._warm.start(tab_id, signal)

    async def discard_warm(self, tab_id: str) -> None:
        """Delete an unconsumed warm task (credit hygiene; no-op when consumed)."""
        await self._warm.discard(tab_id)

    async def solve(self, req: SolveRequest) -> SolveOutcome:
        """Deduped per-tab entry: concurrent callers share one solve."""
        inflight = self._inflight.get(req.tab_id)
        if inflight is not None and not inflight.done():
            return await inflight
        task = asyncio.create_task(self._solve_once(req))
        self._inflight[req.tab_id] = task
        try:
            return await task
        finally:
            self._inflight.pop(req.tab_id, None)

    async def _solve_once(self, req: SolveRequest) -> SolveOutcome:
        settings = self._keys.load()
        if not settings.api_key:
            return _failed("no_key", "no 2Captcha key stored")
        warm = await self._warm.take(req.tab_id, req.signal)
        if warm is not None:
            return await self._run_client(warm[0], req, task_id=warm[1])
        self._stats.record("task_created", host_of(req.signal.page_url))
        return await self._run_client(Captcha2Client(settings.api_key), req)

    async def _run_client(self, client: Captcha2Client, req: SolveRequest,
                          task_id: str = "") -> SolveOutcome:
        """Run one solve on a prepared client; task_id preset when warmed."""
        timeout = int(req.timeout) if req.timeout else self._keys.load().solve_timeout_sec
        try:
            plan = SolvePlan(client=client, ctrl=req.ctrl, tab_id=req.tab_id,
                             signal=req.signal, stop=req.stop or (lambda: False),
                             start=time.monotonic(), stats=self._stats, logger=self._log,
                             page_identity=req.signal.page_identity,
                             challenge_identity=req.signal.challenge_identity)
            if not task_id:
                task_id = await self._create_task(plan)
                if not task_id:
                    return _failed("task_create", "createTask failed", plan)
            return await self._run_task(plan, task_id, timeout)
        finally:
            await client.aclose()

    async def _create_task(self, plan: SolvePlan) -> str:
        task_type = task_type_for(plan.signal.kind)
        payload = task_payload(task_type, plan.signal)
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

    async def _run_task(self, plan: SolvePlan, task_id: str, timeout_sec: int) -> SolveOutcome:
        token, why = await poll_task(plan, task_id, timeout_sec)
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
