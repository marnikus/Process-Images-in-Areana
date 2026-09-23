"""Desktop window discovery — visible windows, their titles and their processes.

Utils leaf: stdlib ctypes only, no app imports. Enumeration and process names
run on Windows; every other platform is a no-op returning [] / "" — a caller
that needs a real window reports that honestly instead of faking a match
(RULE 4). The pure matching helpers work on any OS, so the rules are testable
without Windows.

Sibling of `win_popup` (which raises windows): this module only finds them.
"""

from __future__ import annotations

import sys

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROC_CACHE: dict = {}


def title_has_pattern(title: str, pattern: str) -> bool:
    """Case-insensitive substring match — the user's pattern finds their window."""
    text, want = (title or "").strip().lower(), (pattern or "").strip().lower()
    return bool(text and want) and want in text


def process_matches(name: str, wanted: str) -> bool:
    """Process image name contains `wanted` (case-insensitive; '' matches every process)."""
    want = (wanted or "").strip().lower()
    return not want or want in (name or "").lower()


def pick_matches(windows, pattern: str, proc: str = "") -> list:
    """(hwnd, title) pairs whose process matches and whose title carries the pattern.

    `windows` is an iterable of (hwnd, title, process_name) — injectable, so the
    matching rules are testable on any OS.
    """
    return [(hwnd, title) for hwnd, title, name in (windows or [])
            if process_matches(name, proc) and title_has_pattern(title, pattern)]


def process_name(pid) -> str:
    """Lowercase image name of a pid ('' when unreadable) — cached per process."""
    if sys.platform != "win32" or not pid:
        return ""
    try:
        pid = int(pid)
    except Exception:
        return ""
    if pid not in _PROC_CACHE:
        _PROC_CACHE[pid] = _query_process_name(pid)
    return _PROC_CACHE[pid]


def _query_process_name(pid: int) -> str:
    """Ask the OS for the pid's executable name ('' on any refusal)."""
    import ctypes
    from ctypes import wintypes

    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return (buf.value or "").rsplit("\\", 1)[-1].lower()
            return ""
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""


def _window_title(user32, hwnd) -> str:
    """Window text or '' when unreadable."""
    import ctypes

    try:
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


def visible_windows() -> list:
    """[(hwnd, title, pid)] of visible titled windows (Windows only; [] elsewhere)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        try:
            if user32.IsWindowVisible(hwnd):
                title = _window_title(user32, hwnd)
                if title:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    out.append((hwnd, title, int(pid.value or 0)))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_cb, 0)
    except Exception:
        return []
    return out
