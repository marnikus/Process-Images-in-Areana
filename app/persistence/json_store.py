"""Canonical JSON persistence — one atomic writer, one corrupt-tolerant loader.

Every JSON store in the app (config_manager, preset_store, undo_store,
core/persistence, captcha key_store) used to carry its own copy of the
temp-file-and-replace pattern. This module is the single implementation:

* ``atomic_write_json`` — temp file in the target directory + ``Path.replace``
  (atomic on POSIX and Windows NTFS), optional file mode (0600 for the
  2Captcha key, RULE 20 credential hygiene). No partial file is ever visible.
* ``load_json`` — missing file, unreadable file, non-JSON, or JSON of the
  wrong type all return a deep copy of ``default`` (RULE 13: a bad payload
  costs one failed load, never a crash or a bricked store).
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path | str, data: Any, *, mode: int | None = None, indent: int = 2) -> None:
    """Write ``data`` as JSON to ``path`` atomically (temp + replace)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + "_", suffix=".json.tmp", dir=str(path.parent))
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        tmp_path.replace(path)
        if mode is not None:
            _apply_mode(path, mode)
    finally:
        _cleanup_tmp(tmp_path)


def load_json(path: Path | str, default: Any, *, expect_type: type = dict) -> Any:
    """Load JSON from ``path``; missing/corrupt/wrong-type -> deep-copied default."""
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(default)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return copy.deepcopy(default)
    if not isinstance(data, expect_type):
        return copy.deepcopy(default)
    return data


def _apply_mode(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)  # best effort (no-op failure on some filesystems)
    except Exception:
        pass


def _cleanup_tmp(tmp_path: Path) -> None:
    try:
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass
