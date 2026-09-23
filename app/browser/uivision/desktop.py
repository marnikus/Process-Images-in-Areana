"""Firefox OS windows — find them by the user's pattern and foreground them.

A normal Firefox offers no tab API (that is the whole point of this approach),
so the OS window title is the one honest clue Python has: the running
instance's title carries the page's title, and the user's pattern (the new
window's control element) selects which Firefox is "theirs". Matching and
raising run on Windows through `app/utils/win_find` + `win_popup`; on other
platforms the finder answers zero windows and the runner says so out loud
(RULE 4) — the launch itself works everywhere.
"""

from __future__ import annotations

FIREFOX_PROCESS = "firefox"

# Ui.Vision source (services/desktop_app): the Desktop Automation module —
# XModules2, the native-input half of XClick — listens on ws://127.0.0.1:50889/
# (MCP bridge port + 1). A passive TCP probe is how this app asks "is it
# there?" without speaking the protocol or controlling anything.
DESKTOP_APP_PORT = 50889


DESKTOP_APP_HOST = "127.0.0.1"


def desktop_module_listening(timeout: float = 0.4) -> bool:
    """Something accepts connections on the Desktop Automation module's port."""
    import socket
    try:
        with socket.create_connection((DESKTOP_APP_HOST, DESKTOP_APP_PORT),
                                      timeout=timeout):
            return True
    except OSError:
        return False


def find_windows(pattern: str) -> list:
    """[(hwnd, title)] of Firefox windows whose title carries the pattern."""
    from app.utils import win_find
    if not (pattern or "").strip():
        return []                       # no pattern = no claim about any window
    rows = [(hwnd, title, win_find.process_name(pid))
            for hwnd, title, pid in win_find.visible_windows()]
    return win_find.pick_matches(rows, pattern, FIREFOX_PROCESS)


def foreground(pattern: str) -> tuple:
    """(matches, raised): find the pattern's Firefox windows and put them on top.

    Native OS input (XClick/XType) lands where the user's pointer and focus
    are, so the browser must be visible and foreground before the macro's
    desktop steps run — the owner's critical rule, enforced from both sides
    (here, and `bringBrowserToForeground` inside the macro).
    """
    from app.utils.win_popup import raise_handles
    matches = find_windows(pattern)
    raised = raise_handles([hwnd for hwnd, _title in matches])
    return matches, raised
