"""The Firefox DevTools (RDP) channel — the stealth attach path (2026-09-21).

The app talks to a **manually launched, ordinary Firefox** over the socket that
`--start-debugger-server` opens. That is a different channel from the Remote
Agent (`--remote-debugging-port`), which sets `navigator.webdriver = true` for
the whole session (Firefox bug 1719505) — the signal this round exists to avoid.

What it can do is deliberately narrow: list tabs, evaluate JS, click. There is no
input synthesis, no screenshot, no file chooser — the panel names those gaps
instead of pretending (see the design doc and `browsers.CAPABILITIES`).

Public surface (what the rest of the app imports):

* `Endpoint(host, port)` — the one socket;
* `list_targets` / `evaluate_json` / `click` / `session_info` — `(value, reason)`,
  never raise;
* `probe` — the cheap "is this an RDP server?" question `detect_protocol` asks.
"""

from .client import RdpClient, attach, click, evaluate_json, list_targets, probe, session_info
from .wire import DEFAULT_TIMEOUT, PROTOCOL, RdpError, Endpoint

__all__ = ["Endpoint", "RdpClient", "RdpError", "DEFAULT_TIMEOUT", "PROTOCOL", "attach",
           "click", "evaluate_json", "list_targets", "probe", "session_info"]
