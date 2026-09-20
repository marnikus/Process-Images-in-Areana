"""Default action-block stack — the ONE place that knows what "defaults" means.

2026-10-02 bugfix: an empty `action_blocks` list could reach the session
state (preset import with `[]`, undo of a corrupt snapshot, a failed
snapshot read) and `get_action_blocks` faithfully returned an empty stack.
The UI painted its local defaults, the runner executed nothing — jobs
"finished" instantly with no submit. Healing now happens in one helper.

Layer: core (pure; no I/O, no Qt). `build_default_stack` delegates to the
canonical `BLOCK_DEFINITIONS` / `DEFAULT_STACK_ORDER` in `action_blocks`
so the runner, the UI defaults and this healer can never drift.
CHECK_SECURITY stays in the default set: it is the pipeline's
"detect captcha, pause, never solve" observe block (RULE 20).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from app.core.action_blocks import (
    BLOCK_DEFINITIONS,
    DEFAULT_STACK_ORDER,
    ActionBlock,
    create_default_block,
    stack_to_dicts,
)

REQUIRED_BLOCK_IDS = tuple(bt for bt, d in BLOCK_DEFINITIONS.items() if d.get("required"))


def build_default_stack() -> List[ActionBlock]:
    """Fresh default blocks (new ids every call) in DEFAULT_STACK_ORDER."""
    return [create_default_block(bt) for bt in DEFAULT_STACK_ORDER]


def build_default_dicts() -> List[Dict[str, Any]]:
    """Default stack as JSON-ready dicts (session/preset shape)."""
    return stack_to_dicts(build_default_stack())


def regenerate_ids(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Copy of `blocks` with fresh unique ids (preset re-use never collides)."""
    out: List[Dict[str, Any]] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        copy = dict(b)
        bt = str(copy.get("block_id") or "block").lower()
        copy["id"] = f"{bt}_{uuid.uuid4().hex[:8]}"
        out.append(copy)
    return out


def is_empty_stack(value: Any) -> bool:
    """True for None / [] / "" / a JSON string that is an empty array."""
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    if isinstance(value, str):
        return value.strip() in ("", "[]")
    return False


def heal_stack(stack: List[ActionBlock]) -> List[ActionBlock]:
    """Empty stack → defaults; anything else is returned untouched."""
    return stack if stack else build_default_stack()


def missing_required(stack: List[ActionBlock]) -> List[str]:
    """Required block ids the stack lacks (empty list = complete)."""
    present = {b.block_id for b in stack}
    return [bt for bt in REQUIRED_BLOCK_IDS if bt not in present]
