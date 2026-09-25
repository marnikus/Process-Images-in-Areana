"""Workspace folder IO — temp build, manifest-last commit, atomic publish.

A snapshot exists only when its manifest exists: a crash before the
manifest leaves nothing claiming to be a snapshot; a crash after it leaves
a valid one. Publish is a rename on the same volume (copy fallback across
volumes) with bounded backoff on sharing violations (cloud sync, indexer).
Imports: stdlib only.
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import time
from pathlib import Path

ATTEMPTS = 5
BACKOFF_SEC = 0.05
_TRANSIENT = (errno.EACCES, errno.EBUSY, errno.EPERM)


def sanitize_name(name: str) -> str:
    """Folder-safe snapshot name (filesystem-hostile characters collapsed)."""
    kept = [c if (c.isalnum() or c in "-_ ") else "-" for c in str(name or "workspace")]
    cleaned = "".join(kept).strip().rstrip(".")
    return (cleaned or "workspace")[:60]


def snapshot_dir_name(name: str, utc_struct) -> str:
    """`<name>_<UTC yyyyMMdd-HHMMSS>` — the folder IS the timestamped snapshot."""
    stamp = time.strftime("%Y%m%d-%H%M%S", utc_struct)
    return f"{sanitize_name(name)}_{stamp}"


def new_temp_dir(target: Path) -> Path:
    """Sibling temp folder — never build inside the final folder (design §C.5)."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=target.name + ".tmp-", dir=str(target.parent)))


def _is_transient(exc: OSError) -> bool:
    return isinstance(exc, PermissionError) or exc.errno in _TRANSIENT


def _with_backoff(action) -> None:
    delay = BACKOFF_SEC
    for attempt in range(1, ATTEMPTS + 1):
        try:
            action()
            return
        except OSError as exc:
            if attempt >= ATTEMPTS or not _is_transient(exc):
                raise
        time.sleep(delay)
        delay *= 2


def write_bytes(root: Path, rel: str, data: bytes) -> dict:
    """Write one file inside the (temp) workspace root; returns its integrity entry."""
    from .integrity import bytes_entry

    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return bytes_entry(rel, data)


def copy_tree(src: Path, dst: Path) -> None:
    _with_backoff(lambda: shutil.copytree(str(src), str(dst)))


def _rename(temp: Path, target: Path) -> None:
    _with_backoff(lambda: os.rename(str(temp), str(target)))


def publish(temp: Path, target: Path) -> None:
    """Atomic same-volume rename; cross-volume falls back to copy + rename.

    Raises the original error when the target cannot be created — the temp
    folder survives for inspection and previous snapshots are untouched.
    """
    temp, target = Path(temp), Path(target)
    if target.exists():
        raise FileExistsError(f"target already exists: {target}")
    try:
        _rename(temp, target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    staged = target.with_name(target.name + f".copy-{os.getpid()}")
    copy_tree(temp, staged)
    try:
        _rename(staged, target)
    finally:
        if staged.exists():
            shutil.rmtree(str(staged), ignore_errors=True)


def remove_tree(path: Path) -> bool:
    """Best-effort removal of an unpublished temp folder (never raises)."""
    try:
        shutil.rmtree(str(path))
        return True
    except OSError:
        return False
