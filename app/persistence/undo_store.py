"""UndoStore — global undo timeline persistence (config/undo.json)."""

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

MAX_HISTORY = 100
DEFAULTS = {"history": [], "index": -1}

def _atomic_write(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem+"_", suffix=".json.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(tmp).replace(path)
    finally:
        if Path(tmp).exists():
            try:
                Path(tmp).unlink()
            except:
                pass

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

class UndoStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = _load_json(self.path, DEFAULTS)
        self._clamp()

    def _clamp(self):
        hist = self._data.get("history")
        if not isinstance(hist, list):
            hist = []
        if len(hist) > MAX_HISTORY:
            overflow = len(hist) - MAX_HISTORY
            hist = hist[overflow:]
            idx = self._data.get("index", -1)
            if isinstance(idx, int):
                idx -= overflow
                self._data["index"] = idx
        self._data["history"] = hist
        idx = self._data.get("index")
        if not hist:
            self._data["index"] = -1
        elif not isinstance(idx, int):
            self._data["index"] = len(hist) - 1
        elif idx >= len(hist):
            self._data["index"] = len(hist) - 1
        elif idx < -1:
            self._data["index"] = -1
        self._data["index"] = max(-1, int(self._data.get("index", -1)))

    def load(self):
        self._data = _load_json(self.path, DEFAULTS)
        self._clamp()

    def save(self) -> bool:
        try:
            _atomic_write(self.path, self._data)
            return True
        except Exception:
            return False

    def history(self):
        hist = self._data.get("history", [])
        return copy.deepcopy(hist) if isinstance(hist, list) else []

    def index(self) -> int:
        idx = self._data.get("index", -1)
        return idx if isinstance(idx, int) else -1

    def get(self):
        return self.history(), self.index()

    def set(self, history, index):
        self._data = {
            "history": copy.deepcopy(history) if isinstance(history, list) else [],
            "index": int(index) if isinstance(index, int) else -1,
        }
        self._clamp()
        return self.save()

    def push(self, kind: str, value: Any):
        hist, idx = self.history(), self.index()
        entry = {"kind": kind, "value": copy.deepcopy(value)}
        if idx < len(hist) - 1:
            hist = hist[: idx + 1]
        # avoid duplicate consecutive same entry
        if 0 <= idx < len(hist):
            try:
                if json.dumps(hist[idx], sort_keys=True) == json.dumps(entry, sort_keys=True):
                    return hist, idx
            except Exception:
                pass
        hist.append(entry)
        idx = len(hist) - 1
        if len(hist) > MAX_HISTORY:
            overflow = len(hist) - MAX_HISTORY
            hist = hist[overflow:]
            idx -= overflow
        self.set(hist, idx)
        return hist, idx
