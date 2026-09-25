"""Is a Firefox profile RUNNING right now? — the profile lock Firefox itself holds.

The owner's rule (2026-09-24): only OPEN profiles count — the session
stores of saved-but-closed profiles are stale and must not produce runs.
The one honest, debugger-free receipt is the lock Firefox maintains for
each profile. Source-verified 2026-09-25 (`mozilla-firefox/firefox`,
`toolkit/profile/nsProfileLock.cpp`; the frozen 2025-07 `gecko-dev`
mirror and 2015/2019 vintages agree):

  * Windows: `<profile>/parent.lock` — an EMPTY file opened with
    `CreateFileW` (no sharing) for the process's whole life and NEVER
    deleted (its mtime is Firefox's own startup-crash stamp). The
    liveness receipt is the exclusive handle: while a live Firefox holds
    it, opening the file without sharing fails with
    ERROR_SHARING_VIOLATION / ERROR_ACCESS_DENIED.
  * Linux: `<profile>/.parentlock` — a regular file that PERSISTS after
    clean shutdown; only a live process holds the `fcntl(F_WRLCK)` on it
    (`F_GETLK` answers whether anything is held). Legacy: a `lock`
    SYMLINK `<ip>:<pid>` (old builds; newer builds write `<ip>:+<pid>`
    to mark it obsolete in favour of the fcntl lock).
  * macOS: like Linux (old name `parent.lock`).

There is NO pid-bearing lock file on Windows — the `hostname:pid` lock
text belongs to Thunderbird, not to Firefox. The 2026-09-24 design
assumed Firefox writes `lock.ini` (`hostname:pid`); it does not, and
that assumption is why the first rebuild counted zero profiles as
running. Everything here READS; nothing is written, held or deleted.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

# The lock files a current Firefox holds, per OS, in probe order.
LOCK_FILES = ("parent.lock",) if os.name == "nt" else (".parentlock", "parent.lock")
LEGACY_LINK = "lock"

# Windows CreateFileW probe constants.
_GEN_READ = 0x80000000
_OPEN_EXISTING = 3
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_ERR_ACCESS_DENIED = 5
_ERR_SHARING_VIOLATION = 32

# fcntl lock types agree (F_RDLCK=0, F_WRLCK=1, F_UNLCK=2); F_GETLK differs.
_F_GETLK = 7 if sys.platform == "darwin" else 5
_off_t = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long


class _Flock(ctypes.Structure):
    """`struct flock` — ctypes lays the padding out per platform."""

    _fields_ = [
        ("l_type", ctypes.c_short),
        ("l_whence", ctypes.c_short),
        ("l_start", _off_t),
        ("l_len", _off_t),
        ("l_pid", ctypes.c_int),
    ]


def _held_windows(path: Path) -> bool:
    """Open the lock file without sharing — a live holder is the receipt."""
    kernel32 = getattr(ctypes, "windll", None)
    if kernel32 is None:
        return False
    kernel32.CreateFileW.restype = ctypes.c_void_p
    handle = kernel32.CreateFileW(str(path), _GEN_READ, 0, None, _OPEN_EXISTING, 0, None)
    if handle in (None, 0) or handle == _INVALID_HANDLE:
        return kernel32.GetLastError() in (_ERR_ACCESS_DENIED, _ERR_SHARING_VIOLATION)
    kernel32.CloseHandle(handle)
    return False


def _held_fcntl(path: Path) -> bool:
    """`F_GETLK`: any held lock (ours or another's) means running. The `import fcntl` is
    function-level on purpose: the module does not exist on Windows, and this probe is
    never routed there (`_lock_held` dispatches on `os.name`)."""
    import fcntl
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return False
    try:
        probe = _Flock()
        probe.l_type = 1  # F_WRLCK
        raw = fcntl.fcntl(fd, _F_GETLK, probe)  # the answer comes back as bytes
        if len(raw) != ctypes.sizeof(_Flock):
            return False
        return _Flock.from_buffer_copy(raw).l_type in (0, 1)  # F_RDLCK / F_WRLCK
    except (OSError, ValueError):
        return False
    finally:
        os.close(fd)


def _legacy_link_pid(profile) -> int | None:
    """The old unix `lock` SYMLINK `<ip>:<pid>` (a `+` pid is obsolete)."""
    try:
        target = os.readlink(Path(profile) / LEGACY_LINK)
    except OSError:
        return None
    tail = target.rsplit(":", 1)[-1].strip()
    if tail.startswith("+") or not tail.isdigit():
        return None
    return int(tail)


def _pid_alive_posix(pid: int) -> bool:
    """`kill(pid, 0)` probes existence without signalling (EACCES = alive)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _lock_held(path: Path) -> bool:
    """The real per-OS probe: does a live process hold this lock file?"""
    if os.name == "nt":
        return _held_windows(path)
    return _held_fcntl(path)


def profile_open(profile, checker=None) -> tuple:
    """(open, reason) — the run's gate: closed profiles are never planned or launched.

    `checker` is the lock-held seam (tests): `checker(path) -> bool`.
    """
    probe = checker or _lock_held
    for name in LOCK_FILES:
        path = Path(profile) / name
        if not path.exists():
            continue
        if probe(path):
            return True, f"{name} held — running"
        return False, f"{name} not held — not running"
    if os.name != "nt":
        pid = _legacy_link_pid(profile)
        if pid is not None:
            if _pid_alive_posix(pid):
                return True, f"legacy lock pid {pid} alive — running"
            return False, f"legacy lock pid {pid} not running — stale"
    return False, "no lock file — not running"
