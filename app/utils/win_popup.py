"""Popup-on-top — raise desktop windows whose title matches a tab.

Utils leaf: stdlib ctypes only; the window enumeration itself lives in the
sibling `win_find` (one owner for "which windows exist"). Every non-Windows
platform is a no-op returning 0. All raising is best effort (the OS may
refuse the foreground).
"""

from __future__ import annotations

import sys

from app.utils.win_find import visible_windows

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


def _enum_visible_windows():
    """[(hwnd, title)] of visible titled windows (Windows only)."""
    return [(hwnd, title) for hwnd, title, _pid in visible_windows()]


def _raise_handles(handles) -> int:
    """Restore + foreground each handle; best effort, returns count."""
    import ctypes

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
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


def raise_handles(handles) -> int:
    """Raise already-found window handles (the finder half lives in `win_find`)."""
    if sys.platform != "win32":
        return 0
    try:
        return _raise_handles(handles)
    except Exception:
        return 0
