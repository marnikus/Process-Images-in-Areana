# ideal-size: ~160 lines reason=load-repair-restore trio is one invariant
# ("defaults are always restorable"); splitting hides it (RULE 18.2)
"""Action-block defaults — *always* restorable (BUG 03.2).

Root cause of "all blocks disappeared"
--------------------------------------
`blocks_stack.get_action_blocks()` did:

    raw = bridge.config.get_state("action_blocks", None)
    if raw is None:            return default_stack()
    if isinstance(raw, list):  return load_stack_from_dicts(raw)   # [] -> []

Once anything persisted an **empty list** (delete-all, a failed import, a
truncated session.json), every later load returned an empty stack: the panel
had no blocks and no UI path back, because `reset_action_blocks` was never
wired to a button.

Fix — three guarantees
----------------------
1. `load_blocks()` repairs: empty/corrupt/partial state falls back to defaults.
2. `REQUIRED_BLOCK_IDS` (the image-processing chain, incl. the image solving
   block) are re-inserted in canonical order if a stack is missing them.
3. `restore_default_blocks()` is a first-class slot: full reset, or
   `merge_missing` to keep user blocks and re-add only what is gone.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List

from app.core.action_blocks import (
    DEFAULT_STACK_ORDER,
    create_default_block,
    default_stack,
    load_stack_from_dicts,
    parse_stack_json,
    stack_to_dicts,
)

log = logging.getLogger("arena")

STATE_KEY = "action_blocks"

# The image-processing chain must survive every repair — these are the blocks
# a run cannot work without ("image solving block" = ATTACH -> ... -> SAVE).
REQUIRED_BLOCK_IDS = (
    "OBSERVE_BASELINE",
    "ATTACH_IMAGE",
    "VERIFY_ATTACHMENT",
    "INSERT_PROMPT",
    "VERIFY_PROMPT",
    "SUBMIT",
    "WAIT_OUTPUT",
    "DOWNLOAD",
    "VALIDATE",
    "SAVE",
    "ADVANCE",
)


def _coerce(raw: Any) -> List[Any]:
    """State value -> block list. Unknown shapes become an empty list."""
    if isinstance(raw, list):
        return load_stack_from_dicts(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            return parse_stack_json(raw)
        except (ValueError, TypeError) as exc:
            log.warning("action_blocks JSON unreadable: %s", exc)
    return []


def _order_index(block_id: str) -> int:
    try:
        return DEFAULT_STACK_ORDER.index(block_id)
    except ValueError:
        return len(DEFAULT_STACK_ORDER)


def merge_missing_defaults(stack: List[Any]) -> tuple[List[Any], List[str]]:
    """Re-add required blocks that are absent; returns (stack, added ids).

    Missing blocks are inserted at their canonical position (before the first
    existing block that comes later in DEFAULT_STACK_ORDER). The user's own
    ordering is preserved — repair must not re-sort a working stack.
    """
    present = {getattr(b, "block_id", None) for b in stack}
    added = [bid for bid in REQUIRED_BLOCK_IDS if bid not in present]
    if not added:
        return stack, []
    merged = list(stack)
    for bid in added:
        want = DEFAULT_STACK_ORDER.index(bid)
        pos = len(merged)
        for i, b in enumerate(merged):
            if _order_index(getattr(b, "block_id", "")) > want:
                pos = i
                break
        merged.insert(pos, create_default_block(bid))
    return merged, added


def load_blocks(bridge) -> List[Any]:
    """Self-healing load — never returns an empty stack."""
    try:
        stack = _coerce(bridge.config.get_state(STATE_KEY, None))
    except Exception as exc:  # noqa: BLE001 - corrupted state must not crash boot
        log.warning("action_blocks load failed: %s", exc)
        stack = []
    if not stack:
        log.info("action_blocks empty — restoring default stack")
        return default_stack()
    stack, added = merge_missing_defaults(stack)
    if added:
        log.info("action_blocks repaired, re-added: %s", ", ".join(added))
    return stack


def persist(bridge, stack: List[Any]) -> List[dict]:
    """Write + emit in one place so UI and disk can never disagree."""
    dicts = stack_to_dicts(stack)
    bridge.config.set_state(**{STATE_KEY: dicts})
    payload = json.dumps(dicts, ensure_ascii=False)
    bridge.action_blocks_updated.emit(payload)
    return dicts


class BlocksDefaultsMixin:
    """Slots — declare the `@Slot` wrappers in the Bridge class body (I-06)."""

    def restore_default_blocks(self, merge_missing: bool = False) -> str:
        """Restore the default stack. `merge_missing` keeps custom blocks."""
        try:
            if merge_missing:
                stack, added = merge_missing_defaults(load_blocks(self))
                note = f"re-added {len(added)} default block(s)" if added else "nothing missing"
            else:
                stack, added = default_stack(), list(DEFAULT_STACK_ORDER)
                note = f"restored {len(stack)} default blocks"
            dicts = persist(self, stack)
            self._log(f"🧱 Action blocks: {note}", "success")
            return json.dumps({"ok": True, "added": added, "blocks": dicts},
                              ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            self._log(f"Restore defaults failed: {exc}", "error")
            return json.dumps({"ok": False, "error": str(exc)})

    def get_default_block_catalog(self) -> str:
        """Catalog for the "Add block" menu — id, order, required flag."""
        catalog = [
            {"block_id": bid, "order": idx, "required": bid in REQUIRED_BLOCK_IDS}
            for idx, bid in enumerate(DEFAULT_STACK_ORDER)
        ]
        return json.dumps({"ok": True, "catalog": catalog}, ensure_ascii=False)
