"""Firefox OS windows — find them by the user's pattern and foreground them.

A normal Firefox offers no tab API (that is the whole point of this approach),
so the OS window title is the one honest clue Python has: the running
instance's title carries the ACTIVE tab's title, and the user's pattern (the
new window's control element) selects which Firefox is "theirs". The sharper
half is the session store (`tabs.session_windows`): each window's active title
maps its OS window back to the tabs it holds, so the foreground targets the
ONE window holding the pattern's tab instead of raising every title match.
Matching and raising run on Windows through `app/utils/win_find` + `win_popup`;
on other platforms the finder answers zero windows and the runner says so out
loud (RULE 4) — the launch itself works everywhere.

Delivery choice (2026-09-24 lifecycle redesign): `firefox -P <name> <url>` is
IGNORED when Firefox already runs (the remote command line hands the URL to
the running instance), so `choose_delivery` aims each run WITHOUT remoting —
address-bar delivery into the mapped window (`delivery.deliver_url`), a CLI
cold start (the one case where `-P` works), or the manual fallback. A CLI
launch into a running instance for a non-default profile — the old guaranteed
misfire — is never made.
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


# What Firefox appends to the active tab's title in the OS window title.
FIREFOX_SUFFIXES = ("— mozilla firefox", "- mozilla firefox")
PRIVATE_MARK = "(private browsing)"


def normalize_window_title(title: str) -> str:
    """The OS/session title minus Firefox's own suffix — comparable both ways."""
    text = (title or "").lower().replace(PRIVATE_MARK, "").strip()
    for suffix in FIREFOX_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.strip(" -\t")


def firefox_windows() -> list:
    """[(hwnd, title)] of EVERY Firefox window (unfiltered — the mapping's OS half)."""
    from app.utils import win_find
    rows = [(hwnd, title, win_find.process_name(pid))
            for hwnd, title, pid in win_find.visible_windows()]
    return [(hwnd, title) for hwnd, title, name in rows
            if win_find.process_matches(name, FIREFOX_PROCESS)]


def _titles_match(os_title: str, active_title: str) -> bool:
    """Equal or either-way contains after normalization (both must be non-empty)."""
    left, right = normalize_window_title(os_title), normalize_window_title(active_title)
    return bool(left and right) and (left == right or left in right or right in left)


def _windows_holding(session_windows, pattern: str) -> list:
    """Active titles of session windows holding a pattern-matching tab URL."""
    want = (pattern or "").strip().lower()
    if not want:
        return []
    titles = []
    for window in session_windows or []:
        urls = [str(tab.get("url") or "") for tab in (window or {}).get("tabs", [])]
        if any(want in url.lower() for url in urls):
            title = str(((window or {}).get("active") or {}).get("title") or "")
            if title.strip() and title not in titles:
                titles.append(title)
    return titles


def pick_tab_window(os_windows, session_windows, pattern: str) -> list:
    """OS windows mapped to a session window holding the pattern's tab (pure).

    `os_windows` is `firefox_windows()`' answer, `session_windows`
    `tabs.session_windows()`' — both injectable, so the mapping is testable
    off-Windows. Empty when nothing maps: the runner then falls back to the
    plain title matches instead of claiming a window it cannot prove.
    """
    active = _windows_holding(session_windows, pattern)
    if not active:
        return []
    rows = list(os_windows or [])
    exact = [(hwnd, title) for hwnd, title in rows
             if any(normalize_window_title(title) == normalize_window_title(want)
                    for want in active)]
    if exact:
        return exact                            # exact wins: "Arena Chat" must not steal "Arena"
    return [(hwnd, title) for hwnd, title in rows
            if any(_titles_match(title, want) for want in active)]


def foreground_tab_window(pattern: str, session_windows) -> tuple | None:
    """(matches, raised) for the tab-holding window, or None when unmapped."""
    from app.utils.win_popup import raise_handles
    hits = pick_tab_window(firefox_windows(), session_windows, pattern)
    if not hits:
        return None
    return hits, raise_handles([hwnd for hwnd, _title in hits])


def choose_delivery(run, os_windows, total: int, windows=None) -> tuple:
    """("addressbar", hwnd) | ("cold", "") | ("manual", reason) — never a misfire.

    `run` is the PlannedRun, `os_windows` the `firefox_windows()` answer,
    `total` the sequence length, `windows` the resolver's window map (None =
    the run's whole profile map). An unprofiled fallback run cold-launches
    plainly (no `-P` = no misfire); a mapped profile window gets address-bar
    delivery; a lone profile with nothing running cold-starts with `-P` (the
    ONE case where `-P` works); anything else names why the user must help.
    """
    if not (run.target.profile_dir or "").strip():
        return "cold", ""
    found = list(os_windows or [])
    mapping = list(run.target.windows) if windows is None else list(windows)
    needle = (run.target.url or "").strip()
    hits = pick_tab_window(found, mapping, needle) if found else []
    if hits:
        return "addressbar", hits[0][0]
    if not found:
        if total <= 1:
            return "cold", ""
        return "manual", (f"Firefox is not running and {total} profiles match — "
                          f"a cold start reaches one profile only")
    from .plan import profile_label
    who = profile_label(run.target.profile_name, run.target.profile_dir)
    return "manual", (f"profile “{who}” has no open Firefox window — its tabs "
                      f"are unreachable from here")


