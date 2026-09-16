"""Simple ConfigManager for Arena — handles session and window presets with atomic JSON."""

import json
import os
import copy
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_SESSION = {
    "grid_layout": None,
    "window_states": {"closed": [], "minimized": []},
    "window_geometry": None,
    "theme": "dark",
    "last_folder": "",
    "highlight_duration": 3,
    "cdp_host": "127.0.0.1",
    "cdp_port": 9222,
    "cdp_user_data_dir": "C:\\arena-images-chrome",
    "cdp_extra_args": "",
    # Auto-connect & URL parsing (spec 01-04) — every field storable
    "autoconnect_enabled": True,
    "autoconnect_url_pattern": "arena.ai",
    "autoconnect_interval_ms": 5000,
    "autoconnect_max_pages": 0,
    "autoconnect_primary": True,
    "action_blocks": None,  # will be default stack if None
    "action_blocks_version": 1,
    "watcher_enabled": False,
    "watcher_interval_ms": 2000,
    "watcher_captcha_timeout_sec": 300,
    "watcher_generation_timeout_sec": 600,
    "watcher_auto_pause": True,
    "cooldown_enabled": True,
    "cooldown_min_seconds": 300,
    "cooldown_captcha_penalty_seconds": 900,
}

DEFAULT_WINDOW_PRESETS = {"window_presets": {}}

def _atomic_write(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem+"_", suffix=".json.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(tmp).replace(path)
    finally:
        if Path(tmp).exists():
            try: Path(tmp).unlink()
            except: pass

def _load_json(path: Path, default: Any):
    if not path.exists():
        return copy.deepcopy(default)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return copy.deepcopy(default)
    except Exception:
        return copy.deepcopy(default)

class SessionStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = _load_json(self.path, DEFAULT_SESSION)

    def load(self):
        self._data = _load_json(self.path, DEFAULT_SESSION)

    def save(self):
        _atomic_write(self.path, self._data)

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, **kwargs):
        self._data.update(kwargs)
        self.save()

    def data(self):
        return copy.deepcopy(self._data)

class WindowPresetStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = _load_json(self.path, DEFAULT_WINDOW_PRESETS)
        if "window_presets" not in self._data or not isinstance(self._data["window_presets"], dict):
            self._data["window_presets"] = {}

    def load(self):
        self._data = _load_json(self.path, DEFAULT_WINDOW_PRESETS)
        if "window_presets" not in self._data:
            self._data["window_presets"] = {}

    def save(self):
        _atomic_write(self.path, self._data)

    def list_presets(self):
        result = []
        for name, doc in self._data.get("window_presets", {}).items():
            if not isinstance(doc, dict): continue
            grid = doc.get("grid")
            result.append({
                "name": name,
                "window_count": grid.get("window_count",0) if isinstance(grid, dict) else 0,
                "updated_at": doc.get("updated_at",""),
                "app_version": doc.get("app_version",""),
            })
        result.sort(key=lambda x: (x["updated_at"], x["name"]), reverse=True)
        return result

    def save_preset(self, name: str, document: dict):
        self._data["window_presets"][str(name)] = copy.deepcopy(document)
        self.save()

    def load_preset(self, name: str):
        doc = self._data["window_presets"].get(str(name))
        return copy.deepcopy(doc) if isinstance(doc, dict) else None

    def delete_preset(self, name: str) -> bool:
        key = str(name)
        if key not in self._data["window_presets"]:
            return False
        del self._data["window_presets"][key]
        self.save()
        return True

from .undo_store import UndoStore
from .preset_store import PresetStore

class ConfigManager:
    def __init__(self, config_dir: str = "config"):
        self.dir = Path(config_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.session = SessionStore(self.dir / "session.json")
        self.window_presets = WindowPresetStore(self.dir / "window_presets.json")
        self.undo = UndoStore(self.dir / "undo.json")
        self.presets = PresetStore(self.dir / "arena_presets.json")
        self.session.load()
        self.window_presets.load()
        self.undo.load()
        self.presets.load()

    def get_state(self, key: str, default=None):
        return self.session.get(key, default)

    def set_state(self, **kwargs):
        self.session.set(**kwargs)

    def get_session_data(self):
        return self.session.data()
