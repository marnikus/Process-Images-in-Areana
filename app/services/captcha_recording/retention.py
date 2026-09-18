"""Deterministic count and byte retention for local recording folders."""

from __future__ import annotations

import shutil
from pathlib import Path

MAX_STORED_SESSIONS = 200
MAX_STORAGE_BYTES = 512 * 1024 * 1024


def prune_recordings(root: Path, max_sessions: int = MAX_STORED_SESSIONS,
                     max_bytes: int = MAX_STORAGE_BYTES) -> None:
    """Remove oldest session folders until both configured bounds hold."""
    folders = sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)
    sizes = {folder: _folder_size(folder) for folder in folders}
    total = sum(sizes.values())
    while folders and (len(folders) > max_sessions or total > max_bytes):
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
