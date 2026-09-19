"""UndoService — C5 refactor with predicate helpers and small funcs."""
from __future__ import annotations

from typing import Any

from app.persistence.undo_store import UndoStore

VALID_KINDS = ("grid", "urls", "folder", "queue", "prompt", "settings", "window_states", "arena")


def _filter_by_kind(history, kind: str):
    return [e for e in history if e.get("kind") == kind]


def _find_position_in_filtered(filtered, target):
    for i, e in enumerate(filtered):
        if e == target:
            return i
    return -1


def _find_last_before_idx(history, filtered, kind: str, idx: int) -> int:
    last = -1
    for e in history[: idx + 1]:
        if e.get("kind") == kind:
            pos = _find_position_in_filtered(filtered, e)
            if pos != -1:
                last = pos
    return last


class UndoService:
    def __init__(self, undo_store: UndoStore):
        self.store = undo_store

    def history(self):
        return self.store.get()

    def set_history(self, history, index):
        return self.store.set(history, index)

    def push(self, kind: str, value: Any):
        return self.store.push(kind, value)

    def undo(self):
        hist, idx = self.store.get()
        if idx < 0 or not hist:
            return None
        if idx == 0:
            entry = hist[0] if hist else None
            if entry:
                self.store.set(hist, -1)
                return {
                    "kind": entry["kind"],
                    "value": None,
                    "index": -1,
                    "undone": entry,
                    "empty": True,
                }
            return None
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
        hist, idx = self.store.get()
        return hist, idx

    def set_stack_projection(self, history, index):
        return self.store.set(history, index)

    def kind_projection(self, kind: str):
        hist, idx = self.store.get()
        filtered = _filter_by_kind(hist, kind)
        if not filtered:
            return [], -1
        current = hist[idx] if 0 <= idx < len(hist) else None
        if current and current.get("kind") == kind:
            pos = _find_position_in_filtered(filtered, current)
            if pos != -1:
                return filtered, pos
        last = _find_last_before_idx(hist, filtered, kind, idx)
        return filtered, last

    def push_stack(self, blocks):
        return self.push("arena", blocks)
