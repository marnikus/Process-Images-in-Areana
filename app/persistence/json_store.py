"""Atomic JSON file store — one implementation for every config/*.json file.

Owns: load-with-default + atomic save (temp file + replace, never a
partial file — RULE 13/23 atomicity). Was copied verbatim in
config_manager, preset_store and undo_store; now the single home.
Imports: stdlib only.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    """Read a dict-shaped JSON file; any miss or corruption returns a deep copy of default."""
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


def save_json_atomic(path: Path, data: Any) -> None:
    """Write data via temp file + replace; never leaves a partial or .tmp file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + "_", suffix=".json.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(tmp).replace(path)
    finally:
        if Path(tmp).exists():
            try:
                Path(tmp).unlink()
            except OSError:
                pass
