"""Block + prompt library panel — builtin/custom blocks and prompt presets.

Pure slot moves (no decomposition needed); the custom-entry shaping is a
module function. Imports go panels -> services/core only.
"""

import json
from datetime import datetime
from pathlib import Path

from app.core.action_blocks import get_builtin_blocks_json
from app.ui.qt_compat import Slot


def custom_entry(data: dict) -> dict:
    """Name + timestamp a validated custom-block payload for storage."""
    block = data.get("block", {})
    name = data.get("name") or block.get("custom_name") or block.get("name") or "Custom"
    return {"name": name, "block": data.get("block"),
            "updated_at": datetime.utcnow().isoformat() + "Z"}


class BlocksLibraryMixin:
    """Custom blocks and prompt preset slots."""

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
            entry = custom_entry(data)
            raw = self.config.get_state("custom_blocks", [])
            if not isinstance(raw, list):
                raw = []
            raw = [c for c in raw if c.get("name") != entry["name"]]
            raw.append(entry)
            self.config.set_state(custom_blocks=raw)
            self._log(f"Custom block saved: {entry['name']}", "success")
            return json.dumps({"ok": True, "name": entry["name"]})
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
    def list_prompt_presets(self):
        try:
            presets = self.config.presets.list_prompt_presets()
            return json.dumps(presets, ensure_ascii=False)
        except Exception:
            return "[]"

    @Slot(str, str, result=str)
    def save_prompt_preset(self, name: str, template: str):
        try:
            self.config.presets.save_prompt_preset(name, template)
            self._log(f"Prompt preset saved: {name}", "success")
            return json.dumps({"ok": True})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def load_prompt_preset(self, name: str):
        try:
            doc = self.config.presets.load_prompt_preset(name)
            if not doc:
                return json.dumps({"ok": False, "error": "not found"})
            tmpl = doc.get("template", "")
            self.state.prompt["user_prompt"] = tmpl
            self._save_arena()
            return json.dumps({"ok": True, "template": tmpl})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    @Slot(str, result=str)
    def delete_prompt_preset(self, name: str):
        try:
            if self.config.presets.delete_prompt_preset(name):
                return json.dumps({"ok": True})
            return json.dumps({"ok": False, "error": "not found"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})
