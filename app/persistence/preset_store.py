"""PresetStore for Arena — stores named presets for urls, prompts, settings, etc."""

import copy
from pathlib import Path
from typing import Any

from .json_store import load_json as _load_json, save_json_atomic as _atomic_write

DEFAULTS = {
    "url_presets": [],
    "prompt_presets": {},
    "settings_presets": {},
    "arena_presets": {},
}


class UrlPresetMixin:
    """URL presets (plain list). (W3 split of PresetStore)."""

    # URL presets (list of URLs)
    def get_url_presets(self):
        return copy.deepcopy(self._data.get("url_presets", []))

    def set_url_presets(self, presets):
        self._data["url_presets"] = copy.deepcopy(presets)
        self.save()

    def add_url_preset(self, url: str) -> bool:
        url = (url or "").strip()
        if not url:
            return False
        presets = self._data.get("url_presets", [])
        if url in presets:
            return False
        presets.append(url)
        self._data["url_presets"] = presets
        self.save()
        return True

    def remove_url_preset(self, url: str) -> bool:
        presets = self._data.get("url_presets", [])
        if url not in presets:
            return False
        presets = [p for p in presets if p != url]
        self._data["url_presets"] = presets
        self.save()
        return True


class PromptPresetMixin:
    """Prompt template presets. (W3 split of PresetStore)."""

    # Prompt presets - returns list of names for JS compatibility
    def list_prompt_presets(self):
        data = self._data.get("prompt_presets", {})
        return list(data.keys())

    def list_prompt_presets_detailed(self):
        data = self._data.get("prompt_presets", {})
        return [{"name": k, "template": v.get("template","")[:80]} for k,v in data.items()]

    def save_prompt_preset(self, name: str, template: str):
        if "prompt_presets" not in self._data:
            self._data["prompt_presets"] = {}
        self._data["prompt_presets"][str(name)] = {"template": template}
        self.save()

    def load_prompt_preset(self, name: str):
        return copy.deepcopy(self._data.get("prompt_presets", {}).get(str(name)))

    def delete_prompt_preset(self, name: str) -> bool:
        if str(name) in self._data.get("prompt_presets", {}):
            del self._data["prompt_presets"][str(name)]
            self.save()
            return True
        return False


class SettingsPresetMixin:
    """Settings presets. (W3 split of PresetStore)."""

    # Settings presets
    def list_settings_presets(self):
        data = self._data.get("settings_presets", {})
        return list(data.keys())

    def save_settings_preset(self, name: str, settings: dict):
        if "settings_presets" not in self._data:
            self._data["settings_presets"] = {}
        self._data["settings_presets"][str(name)] = copy.deepcopy(settings)
        self.save()

    def load_settings_preset(self, name: str):
        return copy.deepcopy(self._data.get("settings_presets", {}).get(str(name)))

    def delete_settings_preset(self, name: str) -> bool:
        if str(name) in self._data.get("settings_presets", {}):
            del self._data["settings_presets"][str(name)]
            self.save()
            return True
        return False


class ArenaPresetMixin:
    """Full-snapshot arena presets (sorted by updated_at). (W3 split of PresetStore)."""

    # Arena presets (full snapshot) - list returns names sorted by updated_at desc
    def list_arena_presets(self):
        data = self._data.get("arena_presets", {})
        def _updated(name):
            doc = data.get(name, {})
            return doc.get("updated_at","") if isinstance(doc, dict) else ""
        names = list(data.keys())
        names.sort(key=_updated, reverse=True)
        return names

    def list_arena_presets_detailed(self):
        data = self._data.get("arena_presets", {})
        result = []
        for name, doc in data.items():
            if not isinstance(doc, dict):
                continue
            result.append({
                "name": name,
                "url_count": len(doc.get("urls", [])),
                "image_count": len(doc.get("images", [])),
                "updated_at": doc.get("updated_at",""),
            })
        result.sort(key=lambda x: x["updated_at"], reverse=True)
        return result

    def save_arena_preset(self, name: str, document: dict):
        if "arena_presets" not in self._data:
            self._data["arena_presets"] = {}
        self._data["arena_presets"][str(name)] = copy.deepcopy(document)
        self.save()

    def load_arena_preset(self, name: str):
        return copy.deepcopy(self._data.get("arena_presets", {}).get(str(name)))

    def delete_arena_preset(self, name: str) -> bool:
        if str(name) in self._data.get("arena_presets", {}):
            del self._data["arena_presets"][str(name)]
            self.save()
            return True
        return False


class PresetStore(UrlPresetMixin, PromptPresetMixin, SettingsPresetMixin, ArenaPresetMixin):
    """Persisted preset store (config/arena_presets.json)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = _load_json(self.path, DEFAULTS)
        for k in DEFAULTS:
            if k not in self._data:
                self._data[k] = copy.deepcopy(DEFAULTS[k])

    def load(self):
        self._data = _load_json(self.path, DEFAULTS)
        for k in DEFAULTS:
            if k not in self._data:
                self._data[k] = copy.deepcopy(DEFAULTS[k])

    def save(self):
        _atomic_write(self.path, self._data)

    def all_data(self):
        return copy.deepcopy(self._data)
