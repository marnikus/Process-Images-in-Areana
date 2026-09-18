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

from app.browser.captcha_probes import build_continue_js, build_inject_js

from .api_client import ApiError, Captcha2Client, POLL_INTERVAL_SEC
from .signals import CaptchaSignal, SolveOutcome, host_of

VERIFY_GRACE_SEC = 20.0  # after injection: how long to watch the dialog close

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


def _failed(reason: str, detail: str = "") -> SolveOutcome:
    """Auto attempt failed — caller falls back to the manual wait (RULE 4)."""
    return SolveOutcome(status="auto_failed", reason=f"{reason}: {detail}".strip(": "), method="auto")


def task_type_for(kind: str) -> str:
    return _TASK_TYPES.get(kind, "RecaptchaV2EnterpriseTaskProxyless")


def _task_payload(task_type: str, signal: CaptchaSignal) -> Dict[str, Any]:
    """Docs-exact createTask payload (2captcha.com/api-docs/recaptcha-v2-enterprise)."""
    payload = {"type": task_type,
               "websiteURL": signal.page_url,
               "websiteKey": signal.sitekey}
    if task_type.startswith("RecaptchaV2Enterprise"):
        payload["isInvisible"] = signal.is_invisible  # true = no visible checkbox
    return payload



async def _delete_task(client: Captcha2Client, task_id: str, stats: Any) -> None:
    """Free credit on an abandoned task; best effort, never raises."""
    try:
        if await client.delete_task(task_id):
            stats.record("task_deleted")
    except Exception:
        pass


async def _click_continue(ctrl: Any) -> None:
    """Best effort: the site may auto-submit on token receipt instead."""
    try:
        await ctrl.cdp.evaluate(build_continue_js())
    except Exception:
        pass


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
                             stop=stop, start=time.monotonic())
            return await self._run_task(plan, settings.solve_timeout_sec)
        finally:
            await client.aclose()

    async def _run_task(self, plan: SolvePlan, timeout_sec: int) -> SolveOutcome:
        task_id = await self._create_task(plan)
        if not task_id:
            return _failed("task_create", "createTask failed")
        token, why = await self._poll_task(plan, task_id, timeout_sec)
        if not token:
            await _delete_task(plan.client, task_id, self._stats)
            return _failed(why or "no_token", "no solution token")
        return await self._inject_and_verify(plan, token, task_id)

    async def _inject_and_verify(self, plan: SolvePlan, token: str, task_id: str) -> SolveOutcome:
        if not await self._inject(plan.ctrl, token):
            await _delete_task(plan.client, task_id, self._stats)
            self._auto_fail(plan, "inject", "response field not found on page")
            return _failed("inject", "response field not found on page")
        await _click_continue(plan.ctrl)
        if await self._verify_gone(plan.ctrl, plan.stop):
            return self._solved(plan, task_id)
        await _delete_task(plan.client, task_id, self._stats)
        self._auto_fail(plan, "not_accepted", "dialog still visible after token injection")
        return _failed("not_accepted", "dialog still visible after token injection")

    def _solved(self, plan: SolvePlan, task_id: str) -> SolveOutcome:
        secs = time.monotonic() - plan.start
        self._stats.record("auto_solved", host_of(plan.signal.page_url))
        self._log(f"🤖 2Captcha solved tab {str(plan.tab_id)[:12]} in {secs:.0f}s (token accepted)", "success")
        return SolveOutcome(status="solved", method="auto", task_id=task_id,
                            reason="token accepted", elapsed_sec=secs)

    def _auto_fail(self, plan: SolvePlan, reason: str, detail: str) -> None:
        try:
            self._stats.record("auto_failed", host_of(plan.signal.page_url))
            self._stats.set_last_error(detail[:80])
            self._log(f"🤖 2Captcha auto-solve failed: {reason}", "warn")
        except Exception:
            pass

    async def _create_task(self, plan: SolvePlan) -> str:
        task_type = task_type_for(plan.signal.kind)
        payload = _task_payload(task_type, plan.signal)
        try:
            task_id = await plan.client.create_task(payload)
            self._log(f"🤖 2Captcha task {task_type} submitted (tab {str(plan.tab_id)[:12]}, key=****)", "info")
            return task_id
        except ApiError as e:
            self._stats.record("auto_failed", host_of(plan.signal.page_url))
            self._stats.set_last_error(e.reason)
            self._log(f"🤖 2Captcha createTask failed: {e.reason}", "warn")
            return ""
        except Exception as e:  # fail-open: solver problems never kill the job
            self._log(f"2Captcha createTask unexpected error: {e}", "warn")
            return ""

    def _poll_fail(self, plan: SolvePlan, why: str, detail: str = "") -> Tuple[None, str]:
        self._stats.record("auto_failed", host_of(plan.signal.page_url))
        self._stats.set_last_error(detail or why)
        self._log(f"2Captcha poll ended: {why}", "warn")
        return None, why

    async def _poll_task(self, plan: SolvePlan, task_id: str,
                         timeout_sec: int) -> Tuple[Optional[str], str]:
        """Poll until a token arrives; (None, why) on stop/error/timeout."""
        start = time.monotonic()
        while True:
            if plan.stop():
                self._log("2Captcha polling stopped (user stop)", "info")
                return None, "stopped"
            try:
                res = await plan.client.get_result(task_id)
            except ApiError as e:
                return self._poll_fail(plan, e.reason)
            status = res.get("status")
            if status == "ready":
                return str((res.get("solution") or {}).get("gRecaptchaResponse") or ""), ""
            if status == "failed":
                return self._poll_fail(plan, "task_failed")
            if time.monotonic() - start > timeout_sec:
                return self._poll_fail(plan, "poll_timeout")
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def _inject(self, ctrl: Any, token: str) -> bool:
        try:
            res = await ctrl.cdp.evaluate(build_inject_js(token))
        except Exception as e:
            self._log(f"2Captcha inject probe failed: {e}", "warn")
            return False
        try:
            data = json.loads(res) if isinstance(res, str) else res
            return bool(data and data.get("ok"))
        except Exception:
            return False

    async def _verify_gone(self, ctrl: Any, stop: Callable[[], bool]) -> bool:
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

