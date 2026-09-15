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
        if idx <= 0:
            # if idx == 0, undo to empty state (index -1) and return that entry's undo?
            # For simplicity, if idx ==0, we move to -1 and return previous entry as undo result
            # Actually we want to return the entry that was undone, and new index is idx-1
            if idx == 0:
                # undo first entry -> go to -1, return entry at 0 with index -1
                entry = hist[0] if hist else None
                if entry:
                    self.store.set(hist, -1)
                    return {"kind": entry["kind"], "value": entry["value"], "index": -1, "entry": entry}
            return None
        # idx >0
        new_idx = idx - 1
        # entry that we are undoing is at idx, but we return the state at new_idx? Old system returned the undone entry?
        # We'll return the entry at new_idx as the state to restore, plus the undone entry for info
        self.store.set(hist, new_idx)
        target = hist[new_idx] if 0 <= new_idx < len(hist) else None
        undone = hist[idx] if 0 <= idx < len(hist) else None
        if target:
            return {"kind": target["kind"], "value": target["value"], "index": new_idx, "undone": undone}
        # if new_idx == -1, we return empty with index -1
        return {"kind": "empty", "value": None, "index": -1, "undone": undone}

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
        # find last index of that kind <= current idx
        # simplified: return filtered and its index
        if not filtered:
            return [], -1
        # find position of current pointer's kind
        # if current entry is of this kind, index is its position in filtered
        # else, find last filtered before idx
        current = hist[idx] if 0 <= idx < len(hist) else None
        if current and current.get("kind") == kind:
            # find its position in filtered
            for i, e in enumerate(filtered):
                if e == current:
                    return filtered, i
        # otherwise last filtered before idx
        last = -1
        for i, e in enumerate(hist[: idx + 1]):
            if e.get("kind") == kind:
                # find its position in filtered
                for j, fe in enumerate(filtered):
                    if fe == e:
                        last = j
        return filtered, last

    def push_stack(self, blocks):
        return self.push("arena", blocks)
