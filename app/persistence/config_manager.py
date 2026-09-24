"""Simple ConfigManager for Arena — handles session and window presets with atomic JSON."""

import copy
from pathlib import Path
from typing import Any

from .json_store import load_json as _load_json, save_json_atomic as _atomic_write

DEFAULT_SESSION = {
    "grid_layout": None,
    "window_states": {"closed": [], "minimized": []},
    "window_geometry": None,
    "theme": "dark",
    "last_folder": "",
    "highlight_duration": 3,
    "cdp_host": "127.0.0.1",
    "cdp_port": 9222,  # the BASE port: each browser listens on base + its registry offset
    "cdp_user_data_dir": "C:\\arena-images-chrome",
    "cdp_extra_args": "",
    "active_browser": "chrome",  # which browser the automation connects to and the panel edits
    "cdp_browsers": {},  # per-browser {user_data_dir, extra_args, enabled} overrides
    "url_pattern": "arena.ai",  # one pattern for every browser
    "url_reconcile_interval_ms": 5000,  # S6: Python URL reconciler cadence (clamped 500…60000)
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
    "firefox_auto": {  # the "Firefox auto with Extension" window (I-63): Ui.Vision framework test
        # The macro reuses the tab the search finds and NEVER opens a page
        # (2026-09-23, owner rule) — so there is no "url" field any more; the
        # retired key is dropped on validate so old session.json files heal.
        "pattern": "Arena",          # Firefox tab-title substring ('' = any title)
        "url_pattern": "",           # tab-URL substring ('' = any URL; 2026-09-24 owner option)
        "target": "xpath=//a[span[text()='New Chat']]",  # the XClick locator (cmd_var2)
        "macro": "Python_XClick_Demo",
        "storage": "xfile",          # hard drive (XModule) | browser (import the macro once)
        "home": "",                  # XModule home folder ('' = <User Desktop>/uivision)
        "binary": "",                # Firefox binary ('' = this OS's default)
        "timeout_sec": 90,           # how long one run waits for the savelog file (15…600)
        "pause_ms": 3000,            # wait for the element + show the RED rect (500…30000)
        "selected_profiles": [],     # profile dirs checked in the UI ([] = every profile)
        "skip_no_match": False,      # True = skip a profile with no matching tabs; False = wait
        "wait_timeout_sec": 60,      # when skip_no_match is off, how long to wait for the user to open a tab (10…300)
        "inter_run_delay_sec": 3,    # seconds to wait between runs (gives Firefox time to process)
    },
}

DEFAULT_WINDOW_PRESETS = {"window_presets": {}}

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
