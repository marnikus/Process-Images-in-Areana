"""Disk-safety retention and folder layout for local recording roots.

Two layouts coexist so pre-existing records keep working:
  legacy flat  root/<session_id>/            (session ids are time-prefixed)
  per-day      root/YYYY-MM-DD/<session_id>/ (day derived from the id stamp)
Session count is deliberately NOT bounded here: every recorded session stays
visible in the Records window (all-retained list + per-row delete). Only the
byte cap acts as a safety valve against unbounded disk growth.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Optional

MAX_STORAGE_BYTES = 512 * 1024 * 1024
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def day_dirs(root: Path) -> list[Path]:
    """Per-day folders under the root, oldest first."""
    if not root.exists():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and _DAY.match(p.name)),
                  key=lambda p: p.name)


def session_folders(root: Path) -> list[Path]:
    """Session folders across both layouts, oldest first (ids are time-prefixed)."""
    if not root.exists():
        return []
    found = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if _DAY.match(child.name):
            found.extend(sub for sub in child.iterdir() if sub.is_dir())
        else:
            found.append(child)
    return sorted(found, key=lambda p: p.name)


def is_valid_session_id(session_id: str) -> bool:
    """Session ids are single path segments; '.'/'..' are traversal (D5).

    Path("..").name == "..", so the name check alone would let dot-segments
    resolve to the recordings' parent directory.
    """
    return (bool(session_id)
            and Path(session_id).name == session_id
            and session_id not in (".", ".."))


def find_session_folder(root: Path, session_id: str) -> Optional[Path]:
    """Locate one session in the legacy-flat or per-day layout; None when absent."""
    legacy = root / session_id
    if legacy.is_dir():
        return legacy
    for day in day_dirs(root):
        candidate = day / session_id
        if candidate.is_dir():
            return candidate
    return None


def prune_recordings(root: Path, max_bytes: int = MAX_STORAGE_BYTES) -> None:
    """Remove oldest session folders until the disk safety bound holds."""
    folders = session_folders(root)
    sizes = {folder: _folder_size(folder) for folder in folders}
    total = sum(sizes.values())
    while folders and total > max_bytes:
        oldest = folders.pop(0)
        total -= sizes[oldest]
        shutil.rmtree(oldest, ignore_errors=True)
        drop_empty_day(root, oldest.parent)


def drop_empty_day(root: Path, day: Path) -> None:
    """Remove a per-day folder that lost its last session."""
    if day == root or not day.is_dir() or any(day.iterdir()):
        return
    shutil.rmtree(day, ignore_errors=True)


def _folder_size(folder: Path) -> int:
    total = 0
    for path in folder.rglob('*'):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total
