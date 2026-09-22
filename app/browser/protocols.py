"""Protocol names + the rule about which tab handles can be dialled.

Why this module exists (2026-09-21, round 8): the panel layer has to decide
things like "can this tab be connected as a socket of its own?" without naming a
browser, and it must not import the browser layer at module level. It asks this
leaf module instead, so adding a browser never edits a UI file — the same reason
`browsers.py` is the only place a browser name is written down.

The one rule here is honest rather than clever: an `rdp://` handle is **not** a
socket. Firefox's DevTools server keeps a single socket for the whole browser and
its tabs are handles on it, so a tab picker that tried to dial one would fail in
a way nobody could read. Saying so, by name, is the whole point.

Stdlib only — no browser imports, no UI imports.
"""

from __future__ import annotations

import re

PROTOCOL_CDP = "cdp"     # Chrome/Edge devtools, one socket per tab
PROTOCOL_RDP = "rdp"     # Firefox DevTools server, one socket per browser (stealth)
PROTOCOL_BIDI = "bidi"   # Firefox Remote Agent (`--remote-debugging-port`, flagged)

DEFAULT_BROWSER_PORT = 9222    # the socket-per-tab port (Chrome/Edge, ESR Firefox)
DEFAULT_DEBUGGER_PORT = 6000   # Firefox's DevTools server default

RDP_SCHEME = "rdp://"
_URL_PORT = re.compile(r"://[^/:]+:(\d+)")


def port_in(ws_url) -> int:
    """The port a handle names (0 when it names none or says something odd)."""
    match = _URL_PORT.search(str(ws_url or ""))
    if not match:
        return 0
    try:
        return int(match.group(1))
    except Exception:
        return 0


def refuses_tab_socket(ws_url, endpoint_port=None) -> bool:
    """True when this tab handle cannot become a socket of its own.

    Only one case today, and it is structural rather than a guess: RDP shares one
    socket across every tab, so its handles are not connectable URLs.
    """
    return str(ws_url or "").startswith(RDP_SCHEME)


def connect_refusal(ws_url, endpoint_port=None) -> str:
    """Why this tab cannot be connected as a socket — "" when it can."""
    if not refuses_tab_socket(ws_url, endpoint_port):
        return ""
    return (f"{ws_url} is a Firefox DevTools tab handle — RDP uses ONE socket for the whole "
            "browser, per tab there is nothing to dial. Keep the browser on Firefox and use "
            "Refresh / Diagnose: the app attaches per action and detaches again.")
