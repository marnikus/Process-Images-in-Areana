"""The protocol names themselves — the vocabulary every layer shares.

Leaf module (stdlib only, no browser or UI imports) so a panel can name a channel
without importing the browser layer, and `browsers.py` stays the only place a
browser name is written down.

Round 8 also kept the "can this tab handle be dialled?" rule here. Round 9 deleted
it (D-8): an `rdp://` handle *is* attachable — the client opens the browser's own
DevTools socket for it — so the rule had become the bug the owner reported
("i can not connect the Firefox browser"). What each channel can do now lives with
the handles: `attached.refusal(handle, op)`.
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
