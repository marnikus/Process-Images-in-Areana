"""D2/F-B: bounded, token-free semantic milestones for captcha recordings.

Each milestone is a per-phase whitelist of SolveOutcome fields (offsets in
ms, counts, bounded identity strings). The whitelist itself is the I-29/I-32
guarantee — raw tokens are never redacted in place, they are simply not
selected. `assert_token_free` is a backstop that fails closed (raises) if a
credential-shaped string ever reaches a payload.
"""

from __future__ import annotations

import json
from typing import Any

from .sanitize import contains_tokenish

MAX_FIELD_CHARS = 200
MILESTONE_PHASES = frozenset({
    "task_created", "token_ready", "injected", "page_error",
    "dialog_cleared", "acceptance_candidate", "auto_finished", "final",
})

# phase -> outcome attribute whitelist (offsets in seconds -> ms in payload)
_PHASE_FIELDS: dict[str, tuple[str, ...]] = {
    "task_created": ("task_id", "task_created_sec", "page_identity", "challenge_identity"),
    "token_ready": ("task_id", "token_sec", "token_fp", "dialog_at_token",
                    "page_identity", "challenge_identity"),
    "injected": ("inject", "dialog_at_token", "continue_result"),
    "page_error": ("page_error_at_s", "page_error"),
    "dialog_cleared": ("dialog_cleared_sec",),
    "acceptance_candidate": ("dialog_cleared_sec", "inject"),
    "auto_finished": ("status", "reason", "task_id", "polls", "attempts", "token_sec",
                      "page_error_at_s", "page_identity", "challenge_identity"),
    "final": ("status", "reason", "method", "task_id", "polls", "attempts",
              "elapsed_sec", "token_sec", "dialog_at_token", "inject",
              "continue_result", "page_error_at_s", "page_error",
              "task_created_sec", "dialog_cleared_sec",
              "page_identity", "challenge_identity"),
}
_SECOND_FIELDS = frozenset({
    "task_created_sec", "token_sec", "page_error_at_s", "dialog_cleared_sec", "elapsed_sec",
})


def assert_token_free(value: Any) -> None:
    """Raise ValueError when a serialized payload carries a raw token (fail closed)."""
    if contains_tokenish(json.dumps(value, ensure_ascii=False, default=str)):
        raise ValueError("milestone payload contains a credential-shaped string")


def _bounded(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS]
    if isinstance(value, float):
        return round(value, 3)
    return value


def build_milestone(phase: str, outcome: Any, *, offset_ms: int) -> dict[str, Any]:
    """Whitelisted, bounded milestone payload for one phase; fails closed on tokens."""
    if phase not in MILESTONE_PHASES:
        raise ValueError(f"unknown milestone phase: {phase}")
    payload: dict[str, Any] = {"phase": phase, "offset_ms": int(offset_ms)}
    for name in _PHASE_FIELDS[phase]:
        raw = getattr(outcome, name, None)
        if raw is None or raw == "":
            continue
        if name in _SECOND_FIELDS:
            payload[name + "_ms"] = int(round(float(raw) * 1000))
        elif isinstance(raw, (int, float, bool)):
            payload[name] = int(raw)
        else:
            payload[name] = _bounded(str(raw))
    assert_token_free(payload)
    return payload
