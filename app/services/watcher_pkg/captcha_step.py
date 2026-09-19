# ideal-size: ~190 lines reason=one passive per-page cycle (detect -> gate ->
# inject -> verify); splitting would hide the ordering contract (RULE 18.2)
"""Watcher captcha step — the **only** place a captcha is ever solved.

Passive by design: the Watcher never navigates, never clicks "Generate", and
never touches the job chain. Every tick it asks each attached page "do you
show a captcha?" and, if the gate allows, solves that page individually.

Cycle per page (observe -> act once -> verify -> record):
    1. detect   — CDP probe returns a `CaptchaSignal` or None
    2. gate     — `CaptchaGate.solve_if_watcher_on` (off => leave the page alone)
    3. inject   — write the token into the page's callback/response field
    4. verify   — re-probe; captcha gone => success, still there => report bad
    5. record   — per-page result for the Watcher panel

Layer: services -> services/browser probes. No Qt, no UI imports.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.services.captcha.signals import CaptchaSignal, SolveOutcome
from app.services.captcha.watcher_gate import CaptchaGate

log = logging.getLogger("watcher.captcha")

VERIFY_ATTEMPTS = 6
VERIFY_DELAY_SEC = 1.5

# Injected after a solve: fill every known response field, then fire the
# site callback. Kept as one snippet so the page never sees a half state.
INJECT_TOKEN_JS = r"""
(function (token) {
  var touched = [];
  ['g-recaptcha-response', 'h-captcha-response', 'cf-turnstile-response']
    .forEach(function (name) {
      var nodes = document.querySelectorAll('[name="' + name + '"], #' + name);
      nodes.forEach(function (el) {
        el.value = token;
        el.innerHTML = token;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        touched.push(name);
      });
    });
  try {
    var cfg = window.___grecaptcha_cfg;
    if (cfg && cfg.clients) {
      Object.keys(cfg.clients).forEach(function (k) {
        var c = cfg.clients[k];
        JSON.stringify(c, function (key, val) {
          if (typeof val === 'function' && /callback/i.test(key)) {
            try { val(token); touched.push('callback'); } catch (e) {}
          }
          return typeof val === 'object' ? val : undefined;
        });
      });
    }
  } catch (e) {}
  return JSON.stringify({ touched: touched });
})(%TOKEN%);
"""


@dataclass
class PageCaptchaState:
    """What the Watcher panel shows for one page."""

    tab_id: str
    detected_at: float = 0.0
    attempts: int = 0
    last_reason: str = ""
    solved: bool = False

    def as_dict(self) -> dict:
        return {"tab_id": self.tab_id, "attempts": self.attempts,
                "last_reason": self.last_reason, "solved": self.solved,
                "waiting_sec": round(time.time() - self.detected_at, 1)
                if self.detected_at else 0.0}


@dataclass
class CaptchaStepDeps:
    """Params <= 4 rule: everything the step needs travels in one object."""

    gate: CaptchaGate
    probe: Any                      # WatcherCDP — detect/evaluate/overlay
    logger: Any = None
    max_attempts: int = 3
    pages: Dict[str, PageCaptchaState] = field(default_factory=dict)


class WatcherCaptchaStep:
    """One instance per Watcher; holds per-page captcha state."""

    def __init__(self, deps: CaptchaStepDeps):
        self.d = deps
        self._log = deps.logger or (lambda msg, level="info": log.info(msg))

    # ---- public --------------------------------------------------------
    def snapshot(self) -> list[dict]:
        return [p.as_dict() for p in self.d.pages.values()]

    def forget(self, tab_id: str) -> None:
        self.d.pages.pop(tab_id, None)

    async def handle_page(self, cdp, tab_id: str,
                          signal: Optional[CaptchaSignal]) -> Optional[SolveOutcome]:
        """Run the cycle for exactly one page. Never raises."""
        if signal is None:
            self._on_clear(tab_id)
            return None
        state = self.d.pages.setdefault(tab_id, PageCaptchaState(tab_id))
        if not state.detected_at:
            state.detected_at = time.time()
            self._log(f"🛡️ Captcha detected on tab {tab_id[:8]} ({signal.kind})", "warn")
        if not self.d.gate.is_solving_enabled():
            return self._leave_to_user(state)
        if state.attempts >= self.d.max_attempts:
            return self._exhausted(state)
        return await self._attempt(cdp, tab_id, signal, state)

    # ---- cycle steps ---------------------------------------------------
    def _on_clear(self, tab_id: str) -> None:
        state = self.d.pages.get(tab_id)
        if state and not state.solved and state.detected_at:
            self._log(f"🧹 Captcha cleared on tab {tab_id[:8]}", "info")
        self.forget(tab_id)

    def _leave_to_user(self, state: PageCaptchaState) -> SolveOutcome:
        state.last_reason = self.d.gate.why_disabled()
        return SolveOutcome(ok=False, reason=state.last_reason,
                            retryable=False, skipped=True)

    def _exhausted(self, state: PageCaptchaState) -> SolveOutcome:
        state.last_reason = "max_attempts"
        return SolveOutcome(ok=False, reason="max_attempts", retryable=False)

    async def _attempt(self, cdp, tab_id: str, signal: CaptchaSignal,
                       state: PageCaptchaState) -> SolveOutcome:
        state.attempts += 1
        outcome = await asyncio.to_thread(
            self.d.gate.solve_if_watcher_on, tab_id, signal)
        state.last_reason = outcome.reason or ("solved" if outcome.ok else "")
        if not outcome.ok:
            return outcome
        await self._inject(cdp, tab_id, outcome.token)
        cleared = await self._verify(cdp, tab_id)
        state.solved = cleared
        if not cleared:
            state.last_reason = "token_rejected"
            self.d.gate.report(outcome.task_id, good=False)
            return SolveOutcome(ok=False, reason="token_rejected", retryable=True)
        self.d.gate.report(outcome.task_id, good=True)
        self._log(f"✅ Captcha cleared on tab {tab_id[:8]}", "success")
        return outcome

    async def _inject(self, cdp, tab_id: str, token: str) -> None:
        js = INJECT_TOKEN_JS.replace("%TOKEN%", _js_string(token))
        try:
            await self.d.probe.evaluate(cdp, tab_id, js)
        except Exception as exc:  # noqa: BLE001 - page may navigate mid-inject
            self._log(f"Captcha token injection failed: {exc}", "warn")

    async def _verify(self, cdp, tab_id: str) -> bool:
        for _ in range(VERIFY_ATTEMPTS):
            await asyncio.sleep(VERIFY_DELAY_SEC)
            try:
                still_there = await self.d.probe.detect_captcha(cdp, tab_id)
            except Exception:  # noqa: BLE001 - treat probe error as "unknown"
                continue
            if not still_there:
                return True
        return False


def _js_string(value: str) -> str:
    """JSON-safe JS literal (no f-string quoting traps)."""
    import json
    return json.dumps(value or "")
