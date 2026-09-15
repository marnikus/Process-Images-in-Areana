"""User-chosen portable backups, created exclusively; never overwrite an existing file."""

import os
from pathlib import Path

from image_queue.workspace.library_io import preview_import


def save_library_file(path: Path, text: str) -> None:
    preview_import(text)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
