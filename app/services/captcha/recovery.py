"""Post-captcha generation revival — one bounded resubmit when the blocked request died.

Round-5 evidence (user log 11:37–11:40): the spinner stays alive through the
~60 s enterprise solve, the dialog clears at settle, the spinner stops — and
the wait then burns ~2 min on a dead request before timing out. A human would
press Send again; this policy does exactly that, once, under observation.

Layer: services — the job runner arms the policy on the ctrl and the wait
loop consults it through the `resume_gate` attribute (same protocol as
`security_settler`; the browser layer never imports this module).
Fail-open everywhere (RULE 9): any error returns the diag untouched.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("arena")

RESUME_GRACE_SEC = 20.0  # 10 dead polls before a resubmit is even considered
MAX_RESUBMITS = 1  # one revival attempt per generation wait, ever


@dataclass
class ResumePolicy:
    """Per-wait revival budget to keep gate functions ≤4 params (RULE 16)."""

    prompt: str
    grace_sec: float = RESUME_GRACE_SEC
    max_resubmits: int = MAX_RESUBMITS
    resubmits: int = 0
    settled_at: Optional[float] = None
    cancelled: Optional[Callable[[], bool]] = None
    report: Optional[Callable[[str, str], None]] = None


def arm_resume(ctrl: Any, prompt: str, cancelled: Optional[Callable[[], bool]] = None,
               report: Optional[Callable[[str, str], None]] = None) -> ResumePolicy:
    """Install a fresh policy + gate on the ctrl for one generation wait."""
    policy = ResumePolicy(prompt=prompt, cancelled=cancelled, report=report)
    try:
        ctrl._resume_policy = policy
        ctrl.resume_gate = lambda diag: maybe_resume(ctrl, diag)
    except Exception:
        pass
    return policy


def clear_resume(ctrl: Any) -> None:
    """Remove policy + gate (wait end); never raises."""
    for attr in ("_resume_policy", "resume_gate"):
        try:
            if getattr(ctrl, attr, None) is not None:
                delattr(ctrl, attr)
        except Exception:
            pass


def note_settle(ctrl: Any) -> None:
    """Stamp a captcha settle (visible-and-cleared) on the armed policy."""
    try:
        policy = getattr(ctrl, "_resume_policy", None)
        if policy is not None:
            policy.settled_at = time.monotonic()
    except Exception:
        pass


def _report(policy: ResumePolicy, msg: str, level: str = "info") -> None:
    try:
        if policy.report is not None:
            policy.report(msg, level)
            return
    except Exception:
        pass
    try:
        log.info(msg)
    except Exception:
        pass


def _cancelled(policy: ResumePolicy) -> bool:
    try:
        return bool(policy.cancelled()) if policy.cancelled else False
    except Exception:
        return False


def _settle_due(policy: ResumePolicy) -> bool:
    """A settle is armed, budgeted, uncancelled and past its grace."""
    if policy.settled_at is None:
        return False
    if policy.resubmits >= policy.max_resubmits:
        return False
    if _cancelled(policy):
        return False
    return time.monotonic() - policy.settled_at >= policy.grace_sec


def _generation_dead(policy: ResumePolicy, diag: Dict[str, Any]) -> bool:
    """No spinner and no new pixels; a live generation clears the marker."""
    if diag.get("spinning") or int(diag.get("allNew", 0) or 0) > 0:
        policy.settled_at = None
        return False
    return True


async def maybe_resume(ctrl: Any, diag: Dict[str, Any]) -> Dict[str, Any]:
    """One bounded resubmit when a post-settle generation died (else diag)."""
    try:
        return await _maybe_resume(ctrl, diag)
    except Exception:
        return diag


async def _maybe_resume(ctrl: Any, diag: Dict[str, Any]) -> Dict[str, Any]:
    policy = getattr(ctrl, "_resume_policy", None)
    if policy is None or diag.get("ready"):
        return diag
    if not _settle_due(policy) or not _generation_dead(policy, diag):
        return diag
    policy.resubmits += 1
    policy.settled_at = None
    await _resubmit(ctrl, policy)
    return diag


async def _resubmit(ctrl: Any, policy: ResumePolicy) -> None:
    """Re-insert the identical prompt, then Send — one attempt, logged."""
    _report(policy, "🔄 Captcha settled but the generation died (no spinner, no output) — resubmitting once", "warn")
    try:
        ok, msg = await ctrl.insert_prompt(policy.prompt)
        _report(policy, f"🔄 Resubmit prompt re-insert: {msg} ({'ok' if ok else 'FAILED'})", "info")
    except Exception as e:
        _report(policy, f"🔄 Resubmit prompt re-insert failed: {e} — trying Send anyway", "warn")
    try:
        ok, msg = await ctrl.submit()
        _report(policy, f"🔄 Resubmit Send: {msg} ({'ok' if ok else 'FAILED'})", "info" if ok else "warn")
    except Exception as e:
        _report(policy, f"🔄 Resubmit Send failed: {e}", "warn")
