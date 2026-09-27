"""Output wait status line (2026-09-27 D-3) — the wait says what it sees.

Before this, a wait that never saw a usable image was silent until
"Timeout after 120000ms". These states logged nothing: no new image, an empty
page answer, an image still loading, a thrown check. `WaitStatus` logs one
plain-words line when that status changes, at most every STATUS_EVERY_S while
it doesn't, and always when a page check is slow (≥ SLOW_POLL_S).
`timeout_detail` appends the last status to the timeout error.

Imports: turn_probe (summary only).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from .turn_probe import summary

STATUS_EVERY_S = 20.0
SLOW_POLL_S = 5.0

_WORDS = {
    "not_started": "no check has finished yet",
    "turn_generating": "the image is still being generated",
    "generating_spinner_visible": "the image is still being generated",
    "generating_no_new_yet": "generating, no new image yet",
    "turn_no_image": "no finished image in this job's answer yet",
    "turn_image_loading": "this job's image is still loading",
    "no_new": "no new image on the page yet",
    "no_result": "the page did not answer the check",
    "not_complete": "the new image is still loading",
    "zero_width": "the new image is not visible yet",
    "hidden": "the new image is not visible yet",
    "loading": "the new image is still loading",
    "thumbnail_rejected": "only the attachment thumbnail was found (refused as output)",
    "no_exact_below_found_wait_next": "no image below this job's prompt yet",
    "job_id_mismatch_no_matching_image": "the images found belong to another job",
}


def status_text(diag: Optional[Dict[str, Any]]) -> str:
    """Plain words for one check answer, with its evidence in brackets."""
    diag = diag or {}
    reason = str(diag.get("reason") or "unknown")
    words = _WORDS.get(reason, f"check said: {reason[:160]}")
    extra = _evidence(diag)
    return words + (f" ({extra})" if extra else "")


def _evidence(diag: Dict[str, Any]) -> str:
    parts = [str(diag.get("error") or "")[:160]]
    turn = diag.get("turn")
    if diag.get("engine") == "turn":
        turn = summary(diag)
    if isinstance(turn, dict):
        parts.append(_turn_words(turn))
    return "; ".join(p for p in parts if p)


def _turn_words(turn: Dict[str, Any]) -> str:
    if not turn.get("found"):
        return "this job's prompt is not visible in the chat"
    cands = turn.get("candidates") or []
    if not cands:
        return "job prompt found, no large image under it"
    first = cands[0]
    state = "loaded" if first.get("complete") and first.get("w") else "loading"
    return f"job prompt found, {len(cands)} image(s): {first.get('scheme')} {first.get('w')}x{first.get('h')} {state}"


def timeout_detail(last: Optional[Dict[str, Any]]) -> str:
    """' — last check: …' for the timeout error ('' when nothing was checked)."""
    return f" — last check: {status_text(last)}" if last else ""


class WaitStatus:
    """Throttled status lines for one wait."""

    def __init__(self, log_cb: Callable[[str], None], timeout: float, start: float):
        self._log = log_cb
        self._timeout = timeout
        self._start = start
        self._text = ""
        self._at = 0.0

    def note(self, diag: Optional[Dict[str, Any]], poll_s: float) -> None:
        """Hear one check answer; log when new, due or slow (ready answers log themselves)."""
        if not diag or diag.get("ready"):
            return
        now = time.monotonic()
        text = status_text(diag)
        slow = poll_s >= SLOW_POLL_S
        if text == self._text and now - self._at < STATUS_EVERY_S and not slow:
            return
        self._text, self._at = text, now
        tail = f" · slow page check {poll_s:.1f}s" if slow else ""
        self._log(f"⏳ Output check {now - self._start:.0f}s/{self._timeout:.0f}s: {text}{tail}")
