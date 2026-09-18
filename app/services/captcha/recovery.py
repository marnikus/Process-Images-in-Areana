"""Post-captcha generation revival — one bounded resubmit when the blocked request died.

Round-5 evidence (user log 11:37–11:40): the spinner stays alive through the
~60 s enterprise solve, the dialog clears at settle, the spinner stops — and
the wait then burns ~2 min on a dead request before timing out. A human would
press Send again; this policy does exactly that, once, under observation.
Round 6: the death signature (spinner seen, then lost, nothing arrives) is
identical with or without captcha, so the trigger keys on spinner loss —
a slow start (spinner never seen yet) can never fire.

Layer: services — the job runner arms the policy on the ctrl and the wait
loop consults it through the `resume_gate` attribute (same protocol as
`security_settler`; the browser layer never imports this module).
Fail-open everywhere (RULE 9): any error returns the diag untouched.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

log = logging.getLogger("arena")

RESUME_GRACE_SEC = 20.0  # 10 dead polls before a resubmit is even considered
MAX_RESUBMITS = 1  # one revival attempt per generation wait, ever


@dataclass
class ResumePolicy:
    """Per-wait revival budget to keep gate functions ≤4 params (RULE 16)."""

    prompt: str
    image_path: Optional[str] = None
    grace_sec: float = RESUME_GRACE_SEC
    max_resubmits: int = MAX_RESUBMITS
    resubmits: int = 0
    settled_at: Optional[float] = None
    spinner_seen: bool = False
    dead_since: Optional[float] = None
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


def _note_activity(policy: ResumePolicy, diag: Dict[str, Any], now: float) -> None:
    """Live signals stand the triggers down; dead polls start the window."""
    if diag.get("spinning"):
        policy.spinner_seen = True
    if diag.get("spinning") or int(diag.get("allNew", 0) or 0) > 0:
        policy.dead_since = None
        policy.settled_at = None
    elif policy.spinner_seen and policy.dead_since is None:
        policy.dead_since = now


def _revive_reason(policy: ResumePolicy, now: float) -> str:
    """Matured trigger label, or '' when nothing is due yet."""
    if policy.settled_at is not None and now - policy.settled_at >= policy.grace_sec:
        return "Captcha settled but the generation died (no spinner, no output)"
    if (policy.spinner_seen and policy.dead_since is not None
            and now - policy.dead_since >= policy.grace_sec):
        return "Generation stalled (spinner lost, no output)"
    return ""


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
    now = time.monotonic()
    _note_activity(policy, diag, now)
    if policy.resubmits >= policy.max_resubmits or _cancelled(policy):
        return diag
    reason = _revive_reason(policy, now)
    if not reason:
        return diag
    policy.resubmits += 1
    policy.settled_at = None
    policy.dead_since = None
    await _resubmit(ctrl, policy, reason)
    return diag


async def _attachment_missing(verify: Callable, path: str) -> bool:
    """True when the composer no longer shows the attached image."""
    ok, _ = await verify(Path(path).name)
    return not ok


def _attach_outcome(res: Any) -> Tuple[bool, str]:
    """Normalize attach results (tuple or bare bool) to (ok, msg)."""
    if isinstance(res, (tuple, list)):
        ok = bool(res[0]) if res else False
        msg = str(res[1]) if len(res) > 1 else ""
        return ok, msg
    return bool(res), str(res)


async def _reattach(attach: Callable, policy: ResumePolicy, path: str) -> None:
    """Re-attach the image, reporting the outcome."""
    ok, msg = _attach_outcome(await attach(path))
    _report(policy, f"🔄 Resubmit re-attach: {msg} ({'ok' if ok else 'FAILED'})",
            "info" if ok else "warn")


async def _ensure_attachment(ctrl: Any, policy: ResumePolicy) -> None:
    """Re-attach the image when the error state dropped it (fail-open)."""
    path = policy.image_path
    verify = getattr(ctrl, "verify_attachment", None)
    attach = getattr(ctrl, "attach_image", None)
    if not path or verify is None or attach is None:
        return
    try:
        if await _attachment_missing(verify, path):
            await _reattach(attach, policy, path)
    except Exception as e:
        _report(policy, f"🔄 Resubmit re-attach failed: {e}", "warn")


async def _resubmit(ctrl: Any, policy: ResumePolicy, reason: str) -> None:
    """Re-attach, re-insert the identical prompt, then Send — once, logged."""
    _report(policy, f"🔄 {reason} — resubmitting once", "warn")
    await _ensure_attachment(ctrl, policy)
    try:
        ok, msg = await ctrl.insert_prompt(policy.prompt)
        _report(policy, f"🔄 Resubmit prompt re-insert: {msg} ({'ok' if ok else 'FAILED'})", "info")
    except Exception as e:
        _report(policy, f"🔄 Resubmit prompt re-insert failed: {e} — trying Send anyway", "warn")
    try:
        sender = getattr(ctrl, "submit_when_ready", None)
        ok, msg = await sender() if sender is not None else await ctrl.submit()
        _report(policy, f"🔄 Resubmit Send: {msg} ({'ok' if ok else 'FAILED'})", "info" if ok else "warn")
    except Exception as e:
        _report(policy, f"🔄 Resubmit Send failed: {e}", "warn")
