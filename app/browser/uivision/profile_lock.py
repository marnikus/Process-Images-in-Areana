"""Is a Firefox profile RUNNING right now? — its own lock file, read-only.

The owner's rule (2026-09-24): only OPEN profiles count — the session stores of
saved-but-closed profiles are stale and must not produce runs. The one honest,
debugger-free receipt for "running" is the file Firefox itself writes:
`<profile>/lock.ini` (`<hostname>:<pid>`), created when the profile is opened
and deleted on clean shutdown — the same lock the profile manager uses for
"this profile is in use". Everything here READS; nothing is written, controlled
or touched beyond that.

A lock with a dead pid is a stale lock (crashed session) → not running; a
reused pid owned by a non-Firefox process is also a stale lock (Windows checks
the image name best-effort). No lock file at all, or an unreadable one, answers
not running — a running Firefox always rewrites its session store from a valid
lock, and its directory is readable to us (we read its session stores).
"""

from __future__ import annotations

import os
from pathlib import Path

LOCK_FILE = "lock.ini"

# Windows: PROCESS_QUERY_LIMITED_INFORMATION — enough for the image name.
_QUERY_LIMITED = 0x1000
_BUFFER_SIZE = 4096


def lock_pid(profile) -> int | None:
    """The pid in `<profile>/lock.ini` (None when absent or unparseable)."""
    path = Path(profile) / LOCK_FILE
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return _parse_pid(text)


def _parse_pid(text: str) -> int | None:
    """`<anything>:<pid>` → pid, or None (the hostname half is ignored)."""
    tail = text.rsplit(":", 1)[-1].strip()
    if not tail.isdigit():
        return None
    return int(tail)


def pid_alive(pid: int) -> bool:
    """Is a process with this pid running on this OS? (tests inject a checker)."""
    if os.name == "nt":
        return _pid_alive_windows(pid)
    return _pid_alive_posix(pid)


def _pid_alive_posix(pid: int) -> bool:
    """`kill(pid, 0)` probes existence without signalling (EACCES = alive)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_alive_windows(pid: int) -> bool:
    """OpenProcess + image name — a reused pid owned by another app is stale."""
    import ctypes
    kernel32 = getattr(ctypes, "windll", None)
    if kernel32 is None:
        return False
    handle = kernel32.OpenProcess(_QUERY_LIMITED, False, pid)
    if not handle:
        return False
    try:
        buf = ctypes.create_unicode_buffer(_BUFFER_SIZE)
        size = ctypes.c_uint32(_BUFFER_SIZE)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return True                         # alive; the name is unreadable
        return "firefox" in buf.value.lower()
    finally:
        kernel32.CloseHandle(handle)


def profile_open(profile, checker=None) -> tuple:
    """(open, reason) — the run's gate: closed profiles are never planned or launched."""
    pid = lock_pid(profile)
    if pid is None:
        return False, "no lock file — not running"
    is_alive = checker or pid_alive
    if is_alive(pid):
        return True, f"lock pid {pid} alive"
    return False, f"stale lock — pid {pid} not running"
