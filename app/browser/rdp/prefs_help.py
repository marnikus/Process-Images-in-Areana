"""Operator guidance for the Firefox profile prefs (the connection prompt).

`devtools.debugger.prompt-connection` defaults to **true**, so Firefox shows
"An incoming request to permit remote debugging connection was detected" for
every connection it accepts. The app keeps one connection per browser
(`session_cache`), which reduces that to one dialog per Firefox run — but only
turning the pref off removes it entirely.

Nothing here touches the user's profile. Writing into a live profile directory
is unsafe (Firefox rewrites `prefs.js` on exit and can clobber it), so this
module produces *instructions* and the human applies them.

Layer: browser leaf — pure text; no I/O, no Qt, no app imports.
"""

from __future__ import annotations

from typing import List

__all__ = ["PROMPT_PREF", "prompt_help_lines", "user_js_snippet"]

PROMPT_PREF = "devtools.debugger.prompt-connection"


def prompt_help_lines(port: int = 9224) -> List[str]:
    """How to stop the "Incoming Connection" dialog, as log-ready lines."""
    return [
        f'💡 Firefox asks to authorise every debugger connection ("{PROMPT_PREF}").',
        "   The app now holds ONE connection per browser, so you should see it once "
        "per Firefox start, not once per scan.",
        f"   To remove it entirely: open about:config → set {PROMPT_PREF} = false → "
        "restart Firefox.",
        f"   Then relaunch: firefox.exe --start-debugger-server {port}",
    ]


def user_js_snippet() -> str:
    """A `user.js` fragment the operator can paste into their profile folder.

    `user.js` is applied on every start and is not rewritten by Firefox, which
    makes it the safe place for these prefs (unlike `prefs.js`).
    """
    return "\n".join([
        '// Arena — Firefox DevTools attach (I-62/I-64). Place in your profile folder.',
        'user_pref("devtools.debugger.remote-enabled", true);',
        'user_pref("devtools.chrome.enabled", true);',
        f'user_pref("{PROMPT_PREF}", false);',
    ])
