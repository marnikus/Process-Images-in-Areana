"""Undo history panel — global/stack/grid undo slots.

Entry remember/apply/dispatch lives in `ui/services/undo_entries.py`; this
mixin holds the 10 slots plus the two result-projection module functions.
Imports go panels -> services/core only.
"""

import json

from app.ui.qt_compat import Slot
from app.ui.services import undo_entries as entries


def project_stack_result(raw: str) -> str:
    """Undo/redo payload projected to arena values (else null)."""
    try:
        result = json.loads(raw)
        if isinstance(result, dict) and result.get("kind") in (
                "prompt", "arena", "urls", "settings", "queue", "folder"):
            return json.dumps(result.get("value"), ensure_ascii=False)
        return "null"
    except Exception:
        return "null"


def project_grid_result(raw: str) -> str:
    """Undo/redo payload projected to the grid value (else null)."""
    try:
        result = json.loads(raw)
        if isinstance(result, dict) and result.get("kind") == "grid":
            return result.get("value") or "null"
        return "null"
    except Exception:
        return "null"


class UndoHistoryMixin:
    """Global, stack and grid undo slots."""

    @Slot(result=str)
    def get_undo_history(self):
        hist, idx = self.undo_service.history()
        return json.dumps({"history": hist, "index": idx}, ensure_ascii=False)

    @Slot(str, str, result=bool)
    def push_global_history(self, kind: str, value_json: str):
        try:
            try:
                value = json.loads(value_json) if value_json else None
            except json.JSONDecodeError:
                # for grid, value_json is already canonical payload string; keep raw
                value = value_json
            value, ok = entries.coerce_push_value(kind, value)
            if not ok:
                return False
            self.undo_service.push(kind, value)
            entries.remember_global_edit(self, kind, value)
            entries.emit_undo_state(self)
            return True
        except Exception as e:
            import logging
            logging.getLogger("arena").warning(f"push_global_history failed: {e}")
            return False

    @Slot(result=str)
    def undo(self):
        return entries.undo_step(self)

    @Slot(result=str)
    def redo(self):
        result = self.undo_service.redo()
        if not result:
            self._log("⚠ Nothing to redo", "warn")
            entries.emit_undo_state(self)
            return "null"
        entries.apply_undo_entry(self, result)
        entries.emit_undo_state(self)
        self._log(f"↪ Redo {result.get('kind')}", "success")
        return json.dumps(result, ensure_ascii=False)

    @Slot(result=str)
    def get_stack_history(self):
        hist, idx = self.undo_service.stack_projection()
        return json.dumps({"history": hist, "index": idx}, ensure_ascii=False)

    @Slot(str)
    def push_stack_history(self, stack_json: str):
        try:
            blocks = json.loads(stack_json or "[]")
        except json.JSONDecodeError:
            return
        if isinstance(blocks, list):
            self.undo_service.push_stack(blocks)
            entries.emit_undo_state(self)

    @Slot(result=str)
    def undo_stack(self):
        return project_stack_result(self.undo())

    @Slot(result=str)
    def redo_stack(self):
        return project_stack_result(self.redo())

    @Slot(result=str)
    def undo_grid_layout(self):
        return project_grid_result(self.undo())

    @Slot(result=str)
    def redo_grid_layout(self):
        return project_grid_result(self.redo())
