"""Same-directory write/fsync/validate/replace. Exceptions never imply successful persistence."""

import os
import tempfile
from pathlib import Path

from image_queue.persistence.codec import decode_state


def sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return  # Windows has no portable directory-fsync API; file flush is still required.
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=".workspace-", suffix=".partial", dir=path.parent
    )
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        decode_state(staged.read_bytes())
        os.replace(staged, path)
        sync_directory(path.parent)
    finally:
        staged.unlink(missing_ok=True)
