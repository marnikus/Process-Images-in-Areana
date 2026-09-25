"""Phase lines for the Firefox image job (I-65, RULE 2).

Tokens match Chrome's job wording. Pool words use Chrome's status names.
`waiting_user` is the log name of `waiting_captcha` — manual security, not a new state.
"""

from __future__ import annotations

_WARN = frozenset({
    "Submit acknowledgment lost", "Wait failed: timeout", "rejected",
    "Download failed", "Save failed", "Attach failed", "prompt failed",
    "pool error",
})
_OK = frozenset({
    "Attachment verified", "Verified", "Output", "correlated",
    "Downloaded", "Saved", "pool STEADY",
})


def level_for(name: str) -> str:
    """info / success / warn — a failed phase is never a success line (RULE 4)."""
    if name in _OK:
        return "success"
    if name in _WARN:
        return "warn"
    return "info"


def phase(bridge, corr_id: str, name: str, detail: str = "") -> None:
    """One phase line. A missing logger never breaks the job."""
    text = f"[{corr_id}] {name}"
    if detail:
        text = f"{text}: {detail}"
    try:
        bridge._log(text, level_for(name))
    except Exception:
        pass
