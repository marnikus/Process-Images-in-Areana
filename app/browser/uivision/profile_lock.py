"""Firefox profile locks — is this instance running?

Unix `lock` is a symlink `ip:+pid`. Windows `parent.lock` cannot be renamed
onto itself while Firefox holds it. A missing lock is closed, not unknown.
No Qt, no session store — `profiles` decides what to do with the answer.
"""

from __future__ import annotations

import os
from pathlib import Path


def pid_from_lock(target: str) -> int:
    """PID encoded in a Firefox lock symlink (`ip:+pid`), else 0."""
    text = (target or "").strip()
    if ":+" not in text:
        return 0
    try:
        return int(text.rsplit(":+", 1)[1])
    except ValueError:
        return 0


def pid_alive(pid: int) -> bool:
    """True when `pid` is a live process (signal 0 — no signal is sent)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def symlink_pid(profile) -> int:
    """PID named by `<profile>/lock`, else 0 (absent, not a symlink, junk)."""
    try:
        return pid_from_lock(os.readlink(Path(profile) / "lock"))
    except OSError:
        return 0


def rename_locked(rename) -> bool:
    """True when renaming the lock onto itself is refused (someone holds it)."""
    try:
        rename()
    except OSError:
        return True
    return False


def _real_flock(path) -> bool:
    """False when this process could lock the file (nobody else holds it)."""
    import fcntl
    fd = os.open(str(path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def fcntl_locked(path, lock=None) -> bool:
    """True when the lock file exists and a non-blocking exclusive lock fails."""
    if not Path(path).is_file():
        return False
    try:
        return bool((lock or _real_flock)(path))
    except OSError:
        return True


def file_lock_held(path, windows=None) -> bool:
    """True when `parent.lock` / `.parentlock` is held by another process."""
    target = Path(path)
    if not target.is_file():
        return False
    nt = os.name == "nt" if windows is None else windows
    if nt:
        return rename_locked(lambda: os.rename(target, target))
    return fcntl_locked(target)


def profile_is_open(profile, alive=None) -> bool:
    """True when Firefox holds this profile's lock (the instance is running)."""
    check = alive or pid_alive
    if check(symlink_pid(profile)):
        return True
    folder = Path(profile)
    return file_lock_held(folder / "parent.lock") or file_lock_held(folder / ".parentlock")


def safely_open(profile) -> str:
    """'open', 'closed', or 'unknown' when the probe itself fails."""
    try:
        return "open" if profile_is_open(profile) else "closed"
    except Exception:
        return "unknown"
