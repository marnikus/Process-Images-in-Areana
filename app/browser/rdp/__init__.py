"""Firefox DevTools RDP — attach to a manually launched, real-profile browser.

The one remoting channel that does **not** set `navigator.webdriver`:
`--start-debugger-server` starts the DevTools server, while Marionette
(`--marionette`) and the Remote Agent (`--remote-debugging-port`) are what
`Navigator::Webdriver()` actually consults. No geckodriver, Selenium,
Playwright or Puppeteer is involved, the app never launches the browser, and
detaching leaves the session running.

Files (RULE 18.3 — one vocabulary, all change together):

* `framing`   — `<byte-length>:<json>` codec + reply-vs-event shape rules
* `transport` — one socket, one in-flight request, timeout poisons the link
* `session`   — actor tree (`root` → tab → console), click / probe verbs
* `click_js`  — the in-page payloads (click-only scope)
* `stealth`   — the launch constraints as data + preflight checks (I-62)

Layer: browser — leaf modules only; no Qt, no services, no panels.
"""

from __future__ import annotations

from .click_js import build_click_js, build_probe_js, build_webdriver_probe_js
from .framing import FramingError, decode_packets, encode_packet, is_event, is_reply_from
from .session import ClickResult, FirefoxTab, RDPSession
from .stealth import (FORBIDDEN_FLAGS, REQUIRED_PREFS, forbidden_flags, launch_command,
                      required_prefs, stealth_warnings)
from .transport import DEFAULT_PORT, DEFAULT_TIMEOUT, RDPClosed, RDPTransport

__all__ = [
    "ClickResult", "FirefoxTab", "RDPSession",
    "RDPTransport", "RDPClosed", "DEFAULT_PORT", "DEFAULT_TIMEOUT",
    "encode_packet", "decode_packets", "is_event", "is_reply_from", "FramingError",
    "build_click_js", "build_probe_js", "build_webdriver_probe_js",
    "FORBIDDEN_FLAGS", "REQUIRED_PREFS", "forbidden_flags", "required_prefs",
    "launch_command", "stealth_warnings",
]
