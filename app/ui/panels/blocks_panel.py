"""Blocks Panel — Bridge panel mixin (W1.6 split)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
try:
    from PySide6.QtCore import QObject, Signal, Slot
    _qt_core = True
except ImportError:
    _qt_core = False

if not _qt_core:  # headless shim (no PySide6) — exercised by tests/test_qt_shim_fallback.py
    class QObject:
        def __init__(self, *qt_shim_args, **qt_shim_kwargs): pass

    def Signal(*sig_shim_args, **sig_shim_kwargs):
        class _Sig:
            def emit(self, *emit_shim_args, **emit_shim_kwargs): pass
            def connect(self, *connect_shim_args, **connect_shim_kwargs): pass
        return _Sig()

    def Slot(*slot_shim_args, **slot_shim_kwargs):
        def deco(fn): return fn
        return deco

try:
    from PySide6.QtWidgets import QFileDialog
except ImportError:
    QFileDialog = None

import logging

from app.core.action_blocks import default_stack, stack_to_dicts, load_stack_from_dicts, parse_stack_json, validate_stack, create_default_block, get_builtin_blocks_json

log = logging.getLogger("arena")



class ActionBlocksPanel:

    @Slot(result=str)
    def get_action_blocks(self):
        try:
            stack = self._get_action_blocks()
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
            stack = load_stack_from_dicts(data)
            ok, err = validate_stack(stack)
            if not ok:
                return json.dumps({"ok": False, "error": err})
            if self._save_action_blocks(stack):
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
            stack = self._get_action_blocks()
            new_block = create_default_block(block_type)
            stack.append(new_block)
            if self._save_action_blocks(stack):
                self._log(f"Added action block {block_type}", "success")
                return json.dumps({"ok": True, "id": new_block.id})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def reset_action_blocks(self):
        try:
            stack = default_stack()
            if self._save_action_blocks(stack):
                self._log(f"Action blocks reset to default ({len(stack)} blocks)", "info")
                return json.dumps({"ok": True, "count": len(stack)})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_action_block(self, block_id: str):
        try:
            stack = self._get_action_blocks()
            before = len(stack)
            stack = [b for b in stack if b.id != block_id]
            if len(stack) == before:
                stack = [b for b in self._get_action_blocks() if b.block_id != block_id or b.required]
                if len(stack) == before:
                    return json.dumps({"ok": False, "error": "not found"})
            ok, err = validate_stack(stack)
            if not ok:
                return json.dumps({"ok": False, "error": err})
            if self._save_action_blocks(stack):
                self._log(f"Deleted block {block_id}", "info")
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "save failed"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(result=str)
    def get_builtin_blocks(self):
        try:
            payload = get_builtin_blocks_json()
            return payload
        except Exception as e:
            return json.dumps([], ensure_ascii=False)

    @Slot(result=str)
    def get_custom_blocks(self):
        try:
            raw = self.config.get_state("custom_blocks", [])
            if isinstance(raw, list):
                return json.dumps(raw, ensure_ascii=False)
            return json.dumps([], ensure_ascii=False)
        except Exception:
            return json.dumps([], ensure_ascii=False)

    @Slot(str, result=str)
    def save_custom_block(self, block_json: str):
        try:
            data = json.loads(block_json or "{}")
            if not isinstance(data, dict) or "block" not in data:
                return json.dumps({"ok": False, "error": "invalid custom block format, need {name, block}"})
            name = data.get("name") or data.get("block", {}).get("custom_name") or data.get("block", {}).get("name") or "Custom"
            entry = {
                "name": name,
                "block": data.get("block"),
                "updated_at": datetime.utcnow().isoformat() + "Z",
            }
            raw = self.config.get_state("custom_blocks", [])
            if not isinstance(raw, list):
                raw = []
            raw = [c for c in raw if c.get("name") != name]
            raw.append(entry)
            self.config.set_state(custom_blocks=raw)
            self._log(f"Custom block saved: {name}", "success")
            return json.dumps({"ok": True, "name": name})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_custom_block(self, name: str):
        try:
            raw = self.config.get_state("custom_blocks", [])
            if not isinstance(raw, list):
                raw = []
            before = len(raw)
            raw = [c for c in raw if c.get("name") != name]
            if len(raw) == before:
                return json.dumps({"ok": False, "error": "not found"})
            self.config.set_state(custom_blocks=raw)
            self._log(f"Custom block deleted: {name}", "info")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})


class StackPresetsPanel:

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
            from app.core.action_blocks import upsert_stack_preset
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
            from app.core.action_blocks import remove_stack_preset
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
            self._log(f"Action blocks exported to {path}", "success")
            return json.dumps({"ok": True, "path": str(path)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def export_custom_block(self, name: str):
        try:
            raw = self.config.get_state("custom_blocks", [])
            if not isinstance(raw, list):
                return json.dumps({"ok": False, "error": "no custom blocks"})
            for c in raw:
                if c.get("name") == name:
                    payload = json.dumps(c, ensure_ascii=False, indent=2)
                    path = Path("config") / f"custom_block_{name}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(payload, encoding="utf-8")
                    self._log(f"Custom block exported to {path}", "success")
                    return json.dumps({"ok": True, "path": str(path)})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

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
            self._emit_undo_state()

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
        self._emit_undo_state()

    @Slot(result=str)
    def undo_stack(self):
        raw = self.undo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") in ("prompt","arena","urls","settings","queue","folder"):
                return json.dumps(result.get("value"), ensure_ascii=False)
            return "null"
        except Exception:
            return "null"

    @Slot(result=str)
    def redo_stack(self):
        raw = self.redo()
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and result.get("kind") in ("prompt","arena","urls","settings","queue","folder"):
                return json.dumps(result.get("value"), ensure_ascii=False)
            return "null"
        except Exception:
            return "null"


class ActionBlocksIoPanel:
    """Session persistence + emit for the action-blocks stack (W1.6 move)."""

    def _get_action_blocks(self):
        """Load action blocks from session or default."""
        try:
            raw = self.config.get_state("action_blocks", None)
            if raw is None:
                stack = default_stack()
                return stack
            if isinstance(raw, list):
                return load_stack_from_dicts(raw)
            if isinstance(raw, str):
                return parse_stack_json(raw)
            return default_stack()
        except Exception as e:
            log.warning(f"Failed to load action blocks: {e}")
            return default_stack()

    def _save_action_blocks(self, stack):
        try:
            dicts = stack_to_dicts(stack)
            self.config.set_state(action_blocks=dicts)
            payload = json.dumps(dicts, ensure_ascii=False)
            self.action_blocks_updated.emit(payload)
            # Also push to undo
            try:
                self.undo_service.push("action_blocks", dicts)
                self._emit_undo_state()
            except Exception:
                pass
            return True
        except Exception as e:
            log.warning(f"Failed to save action blocks: {e}")
            return False

    def _emit_action_blocks(self):
        try:
            stack = self._get_action_blocks()
            payload = json.dumps(stack_to_dicts(stack), ensure_ascii=False)
            self.action_blocks_updated.emit(payload)
        except Exception as e:
            log.warning(f"emit action blocks failed: {e}")
