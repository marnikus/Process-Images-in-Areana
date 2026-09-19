"""UndoService — global undo timeline for Arena."""

import copy
import json
from typing import Any, Optional

from app.persistence.undo_store import UndoStore, MAX_HISTORY

VALID_KINDS = ("grid", "urls", "folder", "queue", "prompt", "settings", "window_states", "arena")

class UndoService:
    def __init__(self, undo_store: UndoStore):
        self.store = undo_store

    def history(self):
        return self.store.get()

    def set_history(self, history, index):
        return self.store.set(history, index)

    def push(self, kind: str, value: Any):
        if kind not in VALID_KINDS:
            # allow any kind for forward compat, but log
            pass
        return self.store.push(kind, value)

    def undo(self):
        hist, idx = self.store.get()
        if idx < 0 or not hist:
            return None
        if idx == 0:
            # undo first entry -> go to -1, return empty marker with undone info
            # This allows clearing or reverting to default for that kind
            return self._undo_to_start(hist)
        return self._undo_step(hist, idx)

    def _undo_to_start(self, hist):
        """Undo past the first entry: pointer to -1, empty marker result."""
        entry = hist[0] if hist else None
        if not entry:
            return None
        self.store.set(hist, -1)
        return {
            "kind": entry["kind"],
            "value": None,
            "index": -1,
            "undone": entry,
            "empty": True,
        }

    def _undo_step(self, hist, idx):
        """Step one entry back; target state + what was undone."""
        new_idx = idx - 1
        self.store.set(hist, new_idx)
        target = hist[new_idx] if 0 <= new_idx < len(hist) else None
        undone = hist[idx] if 0 <= idx < len(hist) else None
        if target:
            return {
                "kind": target["kind"],
                "value": target["value"],
                "index": new_idx,
                "undone": undone,
            }
        # fallback empty
        return {
            "kind": "empty",
            "value": None,
            "index": -1,
            "undone": undone,
            "empty": True,
        }

    def redo(self):
        hist, idx = self.store.get()
        if idx >= len(hist) - 1:
            return None
        new_idx = idx + 1
        self.store.set(hist, new_idx)
        entry = hist[new_idx] if 0 <= new_idx < len(hist) else None
        if entry:
            return {"kind": entry["kind"], "value": entry["value"], "index": new_idx, "entry": entry}
        return None

    def stack_projection(self):
        """For compatibility: return history filtered to specific kind? Return all."""
        hist, idx = self.store.get()
        return hist, idx

    def set_stack_projection(self, history, index):
        return self.store.set(history, index)

    def kind_projection(self, kind: str):
        hist, idx = self.store.get()
        filtered = [e for e in hist if e.get("kind") == kind]
        if not filtered:
            return [], -1
        # if current entry is of this kind, index is its position in filtered
        current = hist[idx] if 0 <= idx < len(hist) else None
        if current and current.get("kind") == kind:
            pos = _entry_position(filtered, current)
            if pos >= 0:
                return filtered, pos
        # otherwise last filtered before idx
        return filtered, _last_position_before(hist, filtered, kind, idx)

    def push_stack(self, blocks):
        return self.push("arena", blocks)


def _entry_position(filtered: list, entry) -> int:
    """Position of entry in filtered (-1 when absent)."""
    for i, e in enumerate(filtered):
        if e == entry:
            return i
    return -1


def _last_position_before(hist: list, filtered: list, kind: str, idx: int) -> int:
    """Position in filtered of the last kind-entry at or before idx."""
    last = -1
    for e in hist[: idx + 1]:
        if e.get("kind") == kind:
            j = _entry_position(filtered, e)
            if j >= 0:
                last = j
    return last
