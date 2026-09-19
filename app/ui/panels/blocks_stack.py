"""Action-block stack panel — stack CRUD, stack presets, stack history save.

Module functions own load/save/emit (Bridge delegates `_get_action_blocks`
and `_emit_action_blocks` here for the orchestrator/runner seam); the mixin
holds the 11 slots. Imports go panels -> services/core only.

2026-10-02 bugfix: an empty persisted stack is healed to the defaults on
read (and the heal is persisted, so the runner and the UI agree), an
empty save is rejected, and `restore_default_blocks` gives the UI an
explicit, callback-style way back to the defaults.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from app.core.action_blocks import (
    create_default_block,
    default_stack,
    load_stack_from_dicts,
    parse_stack_json,
    remove_stack_preset,
    stack_to_dicts,
    upsert_stack_preset,
    validate_stack,
)
from app.core.action_blocks_defaults import build_default_stack, is_empty_stack
from app.ui.qt_compat import QFileDialog, Slot
from app.ui.services import undo_entries

log = logging.getLogger("arena")


def _parse_saved_stack(raw):
    if isinstance(raw, list):
        return load_stack_from_dicts(raw)
    if isinstance(raw, str):
        return parse_stack_json(raw)
    return default_stack()


def _heal_empty(bridge, raw, reason: str):
    """Persist + announce the default stack when the saved one is unusable."""
    stack = build_default_stack()
    try:
        bridge.config.set_state(action_blocks=stack_to_dicts(stack))
        bridge._log(f"Action blocks: {reason} — restored the default stack ({len(stack)} blocks)", "warn")
    except Exception:
        pass
    return stack


def get_action_blocks(bridge):
    """Load action blocks from session; an empty/corrupt stack heals to defaults."""
    try:
        raw = bridge.config.get_state("action_blocks", None)
        if raw is None:
            return default_stack()
        if is_empty_stack(raw):
            return _heal_empty(bridge, raw, "saved stack was empty")
        stack = _parse_saved_stack(raw)
        if not stack:
            return _heal_empty(bridge, raw, "saved stack had no readable blocks")
        return stack
    except Exception as e:
        log.warning(f"Failed to load action blocks: {e}")
        return default_stack()


def save_action_blocks(bridge, stack) -> bool:
    """Persist the stack, emit, and push an undo snapshot."""
    try:
        dicts = stack_to_dicts(stack)
        bridge.config.set_state(action_blocks=dicts)
        bridge.action_blocks_updated.emit(json.dumps(dicts, ensure_ascii=False))
        try:
            bridge.undo_service.push("action_blocks", dicts)
            undo_entries.emit_undo_state(bridge)
        except Exception:
            pass
        return True
    except Exception as e:
        log.warning(f"Failed to save action blocks: {e}")
        return False


def _remove_block(bridge, block_id: str):
    """Remove by id, else legacy block_id fallback; returns (stack, found)."""
    stack = get_action_blocks(bridge)
    before = len(stack)
    kept = [b for b in stack if b.id != block_id]
    if len(kept) != before:
        return kept, True
    kept = [b for b in get_action_blocks(bridge) if b.block_id != block_id or b.required]
    return kept, len(kept) != before


def emit_action_blocks(bridge) -> None:
    """Re-emit the current stack payload (Bridge delegates here)."""
    try:
        stack = get_action_blocks(bridge)
        payload = json.dumps(stack_to_dicts(stack), ensure_ascii=False)
        bridge.action_blocks_updated.emit(payload)
    except Exception as e:
        log.warning(f"emit action blocks failed: {e}")


def restore_defaults(bridge) -> str:
    """Persist the default stack and reply with it (JSON, never raises)."""
    try:
        stack = build_default_stack()
        if not save_action_blocks(bridge, stack):
            return json.dumps({"ok": False, "error": "save failed"})
        bridge._log(f"Action blocks restored to defaults ({len(stack)} blocks)", "info")
        return json.dumps({"ok": True, "count": len(stack), "blocks": stack_to_dicts(stack)},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


def export_stack_file(bridge, blocks) -> str:
    """Write the stack JSON to disk (dialog, else headless fallback)."""
    try:
        payload = json.dumps(blocks, ensure_ascii=False, indent=2)
        fname = f"arena-action-blocks-{datetime.now().strftime('%Y-%m-%d')}.json"
        if QFileDialog is None:
            path = Path("config") / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        else:
            folder = QFileDialog.getExistingDirectory(None, "Select folder to export action blocks")
            if not folder:
                return json.dumps({"ok": False, "cancelled": True})
            path = Path(folder) / fname
            path.write_text(payload, encoding="utf-8")
        bridge._log(f"Action blocks exported to {path}", "success")
        return json.dumps({"ok": True, "path": str(path)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


class BlocksStackMixin:
    """Action-block stack and stack-preset slots.

    ideal-size: 11 frozen JS slots; validate/wire helpers already live at
    module level — remaining per-slot bodies cannot move without
    scattering slot+helper pairs (R10.10).
    """

    @Slot(result=str)
    def get_action_blocks(self):
        try:
            stack = get_action_blocks(self)
            payload = json.dumps(stack_to_dicts(stack), ensure_ascii=False)
            self.action_blocks_updated.emit(payload)
            return payload
        except Exception as e:
            return json.dumps([], ensure_ascii=False)

    @Slot(str, result=str)
    def save_action_blocks(self, blocks_json: str):
        try:
            data = json.loads(blocks_json or "[]")
            if not isinstance(data, list):
                return json.dumps({"ok": False, "error": "must be array"})
            if not data:
                return json.dumps({"ok": False, "error": "refusing to save an empty stack — use restore_default_blocks"})
            stack = load_stack_from_dicts(data)
            ok, err = validate_stack(stack)
            if not ok:
                return json.dumps({"ok": False, "error": err})
            if save_action_blocks(self, stack):
                self._log(f"Action blocks saved: {len(stack)} blocks", "success")
                return json.dumps({"ok": True, "count": len(stack)})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def add_action_block(self, block_type: str):
        try:
            block_type = (block_type or "").strip().upper()
            if not block_type:
                return json.dumps({"ok": False, "error": "empty block type"})
            stack = get_action_blocks(self)
            new_block = create_default_block(block_type)
            stack.append(new_block)
            if save_action_blocks(self, stack):
                self._log(f"Added action block {block_type}", "success")
                return json.dumps({"ok": True, "id": new_block.id})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def reset_action_blocks(self):
        try:
            stack = default_stack()
            if save_action_blocks(self, stack):
                self._log(f"Action blocks reset to default ({len(stack)} blocks)", "info")
                return json.dumps({"ok": True, "count": len(stack)})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def restore_default_blocks(self):
        """Defaults + the payload in one reply (UI renders without a second round-trip)."""
        return restore_defaults(self)

    @Slot(str, result=str)
    def delete_action_block(self, block_id: str):
        try:
            stack, found = _remove_block(self, block_id)
            if not found:
                return json.dumps({"ok": False, "error": "not found"})
            ok, err = validate_stack(stack)
            if not ok:
                return json.dumps({"ok": False, "error": err})
            if save_action_blocks(self, stack):
                self._log(f"Deleted block {block_id}", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_stack_presets(self):
        try:
            raw = self.config.get_state("stack_presets", [])
            if isinstance(raw, list):
                return json.dumps(raw, ensure_ascii=False)
            return json.dumps([], ensure_ascii=False)
        except Exception:
            return json.dumps([], ensure_ascii=False)

    @Slot(str, result=str)
    def save_stack_preset(self, preset_json: str):
        try:
            data = json.loads(preset_json or "{}")
            if not isinstance(data, dict):
                return json.dumps({"ok": False, "error": "invalid stack preset format, need {name, blocks}"})
            raw = self.config.get_state("stack_presets", [])
            saved = upsert_stack_preset(raw, data.get("name", ""), data.get("blocks", []))
            self.config.set_state(stack_presets=saved)
            name = (data.get("name") or "").strip()
            self._log(f"Stack preset saved: {name} ({len(data.get('blocks') or [])} blocks)", "success")
            return json.dumps({"ok": True, "name": name})
        except ValueError as e:
            return json.dumps({"ok": False, "error": str(e)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_stack_preset(self, name: str):
        try:
            raw = self.config.get_state("stack_presets", [])
            kept, removed = remove_stack_preset(raw, name)
            if not removed:
                return json.dumps({"ok": False, "error": "not found"})
            self.config.set_state(stack_presets=kept)
            self._log(f"Stack preset deleted: {name}", "info")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def export_action_blocks(self, blocks_json: str):
        try:
            blocks = json.loads(blocks_json or "[]")
            if not isinstance(blocks, list) or not blocks:
                return json.dumps({"ok": False, "error": "empty stack"})
            return export_stack_file(self, blocks)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, int)
    def save_stack_history(self, history_json: str, index: int):
        try:
            hist = json.loads(history_json or "[]")
        except json.JSONDecodeError:
            return
        if not isinstance(hist, list):
            return
        if not isinstance(index, int):
            index = -1
        self.undo_service.set_stack_projection(hist, index)
        undo_entries.emit_undo_state(self)
