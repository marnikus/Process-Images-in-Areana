"""Popup-on-top — raise desktop windows whose title matches a tab.

Utils leaf: stdlib ctypes only, no app imports. Enumeration runs on
Windows; every other platform is a no-op returning 0. All raising is
best effort (the OS may refuse the foreground).
"""

from __future__ import annotations

import sys

_CHROME_SUFFIX = " - google chrome"
_SW_RESTORE = 9


def normalize_title(title) -> str:
    """Comparable window/tab title (case/space/chrome-suffix tolerant)."""
    if not isinstance(title, str):
        return ""
    text = title.strip().lower()
    if text.endswith(_CHROME_SUFFIX):
        text = text[: -len(_CHROME_SUFFIX)]
    return text.strip()


def _title_matches(title: str, want: str) -> bool:
    """Equal or either-way contains after normalization."""
    return bool(title and want) and (title == want or want in title or title in want)


def _wanted_titles(wanted) -> list:
    """Normalized non-empty wanted titles."""
    return [w for w in (normalize_title(t) for t in wanted or []) if w]


def _collect_match(hwnd, title, want, picked) -> None:
    """Append the handle when its title matches and is new."""
    if not isinstance(hwnd, int) or hwnd in picked:
        return
    if any(_title_matches(normalize_title(title), w) for w in want):
        picked.append(hwnd)


def pick_windows(windows, wanted) -> list:
    """Handles whose title matches a wanted tab title (deduped)."""
    want = _wanted_titles(wanted)
    picked = []
    if want:
        for hwnd, title in windows or []:
            _collect_match(hwnd, title, want, picked)
    return picked


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


def _enum_callback(out: list, user32):
    """EnumWindows callback collecting visible window titles."""
    import ctypes
    from ctypes import wintypes

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        try:
            if user32.IsWindowVisible(hwnd):
                out.append((hwnd, _window_title(user32, hwnd)))
        except Exception:
            pass
        return True

    return _cb


def _enum_visible_windows():
    """[(hwnd, title)] of visible titled windows (Windows only)."""
    import ctypes

    user32 = ctypes.windll.user32
    out = []
    try:
        cb = _enum_callback(out, user32)
        user32.EnumWindows(cb, 0)
    except Exception:
        return []
    return [(h, t) for h, t in out if t]


def _raise_handles(handles) -> int:
    """Restore + foreground each handle; best effort, returns count."""
    import ctypes

    user32 = ctypes.windll.user32
    raised = 0
    for hwnd in handles or []:
        try:
            user32.ShowWindow(hwnd, _SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            raised += 1
        except Exception:
            pass
    return raised


def raise_window_titles(wanted) -> int:
    """Raise desktop windows matching wanted titles; count raised."""
    want = [t for t in (wanted or []) if normalize_title(t)]
    if sys.platform != "win32" or not want:
        return 0
    try:
        return _raise_handles(pick_windows(_enum_visible_windows(), want))
    except Exception:
        return 0
