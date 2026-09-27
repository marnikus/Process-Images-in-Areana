"""Atomic JSON file store — one implementation for every config/*.json file.

Owns: load-with-default + atomic save (temp file + replace, never a
partial file — RULE 13/23 atomicity). Was copied verbatim in
config_manager, preset_store and undo_store; now the single home.
The replace retries transient Windows sharing violations (cloud-sync /
indexer holding the target — the cooldowns.json access-denied class,
B10) with the same bounded backoff `core/persistence.py` uses for
app_state.json, so every store gets the hardening at once.
Imports: stdlib only.
"""

from __future__ import annotations

import copy
import errno
import functools
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_SEC = 0.02
_TRANSIENT_ERRNOS = (errno.EACCES, errno.EBUSY, errno.EPERM)


def _is_transient(exc: OSError) -> bool:
    """A sharing violation another process (sync client, indexer) will release soon."""
    return isinstance(exc, PermissionError) or exc.errno in _TRANSIENT_ERRNOS


def _transient_or_raise(exc: OSError) -> bool:
    """False for a transient sharing violation; re-raise every other OSError."""
    if _is_transient(exc):
        return False
    raise exc


def _try_replace(tmp_path: Path, target: Path) -> bool:
    """One `replace`; False on a transient failure, any other OSError propagates."""
    try:
        tmp_path.replace(target)
    except OSError as exc:
        return _transient_or_raise(exc)
    return True


def _attempt(replace_once, delay: float) -> bool:
    """One non-final try; on a transient failure wait `delay` before the next one."""
    if replace_once():
        return True
    time.sleep(delay)
    return False


def _replace_retry(tmp_path: Path, target: Path) -> None:
    """`replace` with bounded doubling backoff on transient sharing violations (B10).

    The last attempt runs bare so its error — transient or not — reaches the caller.
    """
    delays = (_REPLACE_BACKOFF_SEC * 2 ** i for i in range(_REPLACE_ATTEMPTS - 1))
    replace_once = functools.partial(_try_replace, tmp_path, target)
    if any(_attempt(replace_once, delay) for delay in delays):
        return
    tmp_path.replace(target)


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
    """Write data via temp file + replace (with transient-failure retry); never leaves a partial or .tmp file behind."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.stem + "_", suffix=".json.tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _replace_retry(Path(tmp), path)
    finally:
        if Path(tmp).exists():
            try:
                Path(tmp).unlink()
            except OSError:
                pass
