"""Which Firefox profiles are actually OPEN — the lockfile is the witness.

A closed profile's sessionstore keeps its LAST session's tabs, so reading
every profile invents runs for windows that don't exist. Firefox holds an
exclusive lock in each RUNNING profile's dir: `parent.lock` on Windows (a
crash leaves it stale-but-openable — the sharing check tells), a
`lock`/`parent.lock` symlink to `IP:+PID` on POSIX (live ⟺ the PID answers).
Never raises: every refusal answers "closed".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_running(profile_dir) -> bool:
    """True when the profile's lock proves a live Firefox (never raises)."""
    try:
        if sys.platform == "win32":
            return _windows_running(profile_dir)
        return _posix_running(profile_dir)
    except Exception:
        return False


def running(dirs) -> list:
    """The dirs whose lock proves a live Firefox (stable order)."""
    return [profile for profile in dirs or [] if is_running(profile)]


def closed(dirs) -> list:
    """The dirs with no live lock — skipped, but said aloud (RULE 4)."""
    return [profile for profile in dirs or [] if not is_running(profile)]


def _windows_running(profile_dir, opener=None) -> bool:
    """`parent.lock` held-open ⟺ running (stale-but-openable after a crash)."""
    lock = Path(profile_dir) / "parent.lock"
    if not lock.exists():
        return False
    attempt = opener or _try_open
    try:
        attempt(lock)
    except PermissionError:
        return True      # sharing violation: Firefox holds it open right now
    except OSError:
        return False
    return False


def _try_open(path) -> None:
    """Open-and-close for write (raises when another process holds it)."""
    fd = os.open(path, os.O_RDWR)
    os.close(fd)


def _lock_pid(target: str):
    """The PID from a `IP:+PID` lock target (None when malformed)."""
    tail = (target or "").rsplit("+", 1)[-1].strip()
    return int(tail) if tail.isdigit() else None


def _posix_running(profile_dir) -> bool:
    """`lock`/`parent.lock` symlink alive ⟺ its PID answers (POSIX)."""
    base = Path(profile_dir)
    for name in ("lock", "parent.lock"):
        link = base / name
        if not link.is_symlink():
            continue
        pid = _lock_pid(os.readlink(link))
        if not pid:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False     # stale lock: the crash left the symlink behind
        except PermissionError:
            return True      # alive, owned by another user: un-signallable
        return True
    return False
