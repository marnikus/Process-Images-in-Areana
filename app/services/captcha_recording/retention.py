"""Disk-safety retention for local recording folders.

Session count is deliberately NOT bounded here: every recorded session stays
visible in the Records window (all-retained list + per-row delete). Only the
byte cap acts as a safety valve against unbounded disk growth.
"""

from __future__ import annotations

import shutil
from pathlib import Path

MAX_STORAGE_BYTES = 512 * 1024 * 1024


def prune_recordings(root: Path, max_bytes: int = MAX_STORAGE_BYTES) -> None:
    """Remove oldest session folders until the disk safety bound holds."""
    folders = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)
    sizes = {folder: _folder_size(folder) for folder in folders}
    total = sum(sizes.values())
    while folders and total > max_bytes:
        oldest = folders.pop(0)
        total -= sizes[oldest]
        shutil.rmtree(oldest, ignore_errors=True)


def _folder_size(folder: Path) -> int:
    total = 0
    for path in folder.rglob('*'):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total
