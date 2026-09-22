"""One handle grammar, three channels — and what each channel can actually do (round 9).

Round 8 taught the *panel* that Firefox speaks the DevTools RDP protocol; the execution client
still asked every endpoint for Chrome's HTTP tab list, which is the owner's log:

    CDP error: URLError http://localhost:9224/json/list: Not Found      (every reconcile pass)

This module is the missing half. A tab **handle** names its own endpoint and channel:

* `ws://host:port/devtools/page/<id>` — CDP, one socket per tab (Chrome/Edge);
* `rdp://host:port/ctx-N` — Firefox's DevTools server, one socket for the whole browser,
  tabs are `ctx-N` handles on it (the stealth channel; no `navigator.webdriver`);
* `ws://host:port/session#<ctx>` — WebDriver BiDi, one *session* for every context, so the
  context has to ride along in the handle (a bare `/session` url is the same string for all
  of them — the round-8 gap).

Everything here answers `(value, reason)` and never raises: the callers are Qt slots and the
job loop. `evaluate` keeps the transport's B8 contract (`last_error` + `last_error_kind`), and
the operations the DevTools protocol does not have (`DOM.*`, `Page.captureScreenshot`,
`Input.dispatchMouseEvent`) refuse **by name** instead of returning a silent `None`.

RULE 18: file ≤300, funcs ≤20, ≤3 params.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from . import bidi, browsers, protocols, rdp
from .protocols import PROTOCOL_BIDI, PROTOCOL_CDP, PROTOCOL_RDP

__all__ = ["Answer", "Handle", "ScanNote", "PROTOCOL_CDP", "PROTOCOL_RDP", "PROTOCOL_BIDI",
           "attach", "attach_hint", "block", "diagnose", "endpoint_handle", "evaluate",
           "explain_failure", "handle_of", "is_remote", "list_rows", "local_url", "parse_handle",
           "refusal", "row_key", "scan_line", "tab_identity"]

DEFAULT_TIMEOUT = 5.0
GREETING_WAIT = 0.6
CAPABILITY_KIND = "capability"   # why a refused operation failed (B8 keeps js/protocol/transport)
RDP_PREFIX = f"{PROTOCOL_RDP}://"
_PAGE_ID = re.compile(r"/devtools/page/([^/]+)$")
_SESSION = re.compile(r"/session/?$")
_URL = re.compile(r"^(?P<scheme>[a-z][a-z0-9+.-]*)://(?:(?P<host>[^/@:]+))?(?::(?P<port>\d+))?(?P<path>/[^?#]*)?(?:#(?P<frag>.*))?$")


@dataclass(frozen=True)
class Handle:
    """One tab (or one browser endpoint) as its own channel describes it."""

    ws_url: str = ""
    channel: str = PROTOCOL_CDP
    host: str = "127.0.0.1"
    port: int = 9222
    tab_id: str = ""
    browser: str = ""

    @property
    def label(self) -> str:
        """How a log line names it: the tab id, else the endpoint."""
        return self.tab_id or f"{self.host}:{self.port}"

    def with_browser(self, browser_id: str) -> "Handle":
        """The same handle, now knowing which registry row it belongs to."""
        return Handle(self.ws_url, self.channel, self.host, self.port, self.tab_id, browser_id or "")


@dataclass(frozen=True)
class Answer:
    """One `evaluate` outcome, in the shape the transport already promises."""

    value: Any = None
    error: str = ""
    kind: str = ""      # "" | js | protocol | transport | timeout


@dataclass(frozen=True)
class ScanNote:
    """One browser that could not be listed: what it is, where, and what to do."""

    browser: str
    host: str
    port: int
    reason: str
    protocol: str = ""

    @property
    def line(self) -> str:
        """The one line a scan logs for this browser (D-6)."""
        return f"· {self.browser} on {self.host}:{self.port} — {self.reason}"


# ── the grammar ──────────────────────────────────────────────────────────────


def _channel_of(scheme: str, path: str, frag: str) -> str:
    """Which channel a URL describes (the scheme, then the path, decide)."""
    if scheme == PROTOCOL_RDP:
        return PROTOCOL_RDP
    if scheme in ("ws", "wss") and _SESSION.search(path or ""):
        return PROTOCOL_BIDI
    return PROTOCOL_CDP


def _tab_id_of(channel: str, path: str, frag: str) -> str:
    """The tab identity inside a handle: `ctx-N`, a page id, or a context id."""
    if channel == PROTOCOL_RDP:
        return (path or "").strip("/")
    if channel == PROTOCOL_BIDI:
        return frag or ""
    match = _PAGE_ID.search(path or "")
    return match.group(1) if match else ""


def parse_handle(ws_url, host: str = "127.0.0.1", port: int = 9222) -> Handle:
    """One url → the channel, the endpoint and the tab it means (never raises).

    The `host`/`port` arguments are the fallback for a url that names neither (an
    empty url, a scheme-only handle), which is how the pool's own endpoint stays
    the default for a tab whose url was never fully written out.
    """
    text = str(ws_url or "").strip()
    match = _URL.match(text)
    if not match:
        return Handle(text, PROTOCOL_CDP, host, int(port), "")
    parts = match.groupdict()
    channel = _channel_of(str(parts["scheme"]), str(parts["path"] or ""), str(parts["frag"] or ""))
    return Handle(text, channel, str(parts["host"] or host),
                  int(parts["port"] or port), _tab_id_of(channel, str(parts["path"] or ""),
                                                         str(parts["frag"] or "")))


def endpoint_handle(host: str, port: int, channel: str, browser_id: str = "") -> Handle:
    """A handle that means "this browser's endpoint" (listing, never attaching)."""
    channel = channel or PROTOCOL_CDP
    return Handle(f"{channel}://{host}:{int(port)}/", channel, host, int(port), "", browser_id or "")


def is_remote(handle: Optional[Handle]) -> bool:
    """True when the tab rides the browser's own socket (RDP/BiDi, not one per tab)."""
    return bool(handle) and handle.channel in (PROTOCOL_RDP, PROTOCOL_BIDI)


def handle_of(transport) -> Optional[Handle]:
    """The channel a live transport is attached to (None = a plain CDP websocket)."""
    return getattr(transport, "_attachment", None)


def local_url(ws_url: str, handle: Handle) -> str:
    """The url to connect with, falling back to the handle's own endpoint."""
    return ws_url or f"ws://{handle.host}:{handle.port}/devtools/page/{handle.tab_id}"


# ── attach / list / diagnose ─────────────────────────────────────────────────


def _profile_of(handle: Handle):
    """The registry row this handle belongs to (by id, else by its channel)."""
    return browsers.profile_of(handle.browser) or browsers.profile_for_protocol(handle.channel)


def _tab_ids(rows: List[Any]) -> str:
    return ", ".join(r.id for r in rows) or "none"


def attach(handle: Handle, timeout: float = DEFAULT_TIMEOUT) -> Tuple[bool, str]:
    """Open (and immediately close) the channel of this tab — is it really there?

    Attaching never touches the browser process: it is one socket to the DevTools
    server, a `listTabs`, and a close. The browser keeps running with every tab.
    """
    if handle.channel == PROTOCOL_RDP:
        return _attach_rdp(handle, timeout)
    if handle.channel == PROTOCOL_BIDI:
        return False, (f"BIDI cannot attach a tab: the Remote Agent has one session socket for every "
                       f"context ({handle.ws_url}). Restart Firefox with --start-debugger-server "
                       f"<port> to use the DevTools channel this app works with.")
    return True, ""


def _attach_rdp(handle: Handle, timeout: float) -> Tuple[bool, str]:
    """Attach to one Firefox tab, or say which tabs Firefox does have."""
    rows, err = rdp.list_targets(rdp.Endpoint(handle.host, handle.port), timeout)
    if err and not rows:
        return False, explain_failure(handle, _profile_of(handle), timeout)
    ids = [r.id for r in rows]
    if handle.tab_id and handle.tab_id not in ids:
        return False, (f"no tab {handle.tab_id!r} in Firefox at {handle.host}:{handle.port} — "
                       f"it lists: {_tab_ids(rows)}. Refresh the tab list (the tab may have closed).")
    return (True, "") if ids or not handle.tab_id else (True, "")


def list_rows(handle: Handle, timeout: float = DEFAULT_TIMEOUT) -> Tuple[List[Any], str]:
    """This endpoint's tabs over its own channel (never HTTP on a DevTools socket)."""
    from . import endpoints      # lazy: endpoints reads this module for its failure reasons

    profile = _profile_of(handle)
    if profile is None:
        return [], f"no browser registry row speaks {handle.channel!r}"
    return endpoints.list_targets(profile.id, handle.host, handle.port, timeout)


def _rdp_session_line(handle: Handle, timeout: float) -> str:
    """The DevTools session's own facts — application, actor prefix, tab count (D-7).

    Round 8's panel logged these from `rdp.session_info`; keeping them here means the
    diagnose the client routes to (and the panel renders) carries the same facts for a
    Firefox endpoint as it does for a CDP one.
    """
    info, err = rdp.session_info(rdp.Endpoint(handle.host, handle.port), timeout)
    if err or not isinstance(info, dict):
        return ""
    return (f"{info.get('application', 'browser')} session, {info.get('tabs', 0)} tab(s), "
            f"actor prefix {info.get('prefix', '')}* (actors are re-resolved on every attach)")


def diagnose(handle: Handle, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """The `diagnose_sync` shape the panel already renders, for any channel."""
    rows, err = list_rows(handle, timeout)
    profile = _profile_of(handle)
    label = profile.label if profile else handle.channel.upper()
    facts = _rdp_session_line(handle, timeout) if not err and handle.channel == PROTOCOL_RDP else ""
    check = {"host": handle.host, "port": handle.port, "port_open": bool(rows) or not err,
             "list_count": len(rows), "list_error": err, "version_error": ""}
    summary = (f"✅ {label} — {handle.channel.upper()} on {handle.host}:{handle.port}: "
               f"{len(rows)} tab(s)" + (f", {facts}" if facts else "")) if not err else f"❌ {err}"
    return {"host": handle.host, "port": handle.port, "checks": [check],
            "tabs": [{"id": r.id, "title": r.title, "url": r.url, "ws_url": r.ws_url} for r in rows],
            "summary": summary}


# ── evaluate (the one operation every channel has) ───────────────────────────


def evaluate(handle: Handle, expression: str, timeout: float = DEFAULT_TIMEOUT) -> Answer:
    """Run JS in one tab, whatever channel it is on — `Answer`, never an exception."""
    if handle.channel == PROTOCOL_RDP:
        return _evaluate_rdp(handle, expression, timeout)
    if handle.channel == PROTOCOL_BIDI:
        return _evaluate_bidi(handle, expression, timeout)
    return Answer(None, f"a CDP handle evaluates over its own websocket, not here ({handle.ws_url})",
                  "protocol")


def _evaluate_rdp(handle: Handle, expression: str, timeout: float) -> Answer:
    """One JS evaluation over the DevTools socket (a page exception is `kind='js'`)."""
    point = rdp.Endpoint(handle.host, handle.port)
    try:
        with rdp.attach(point, timeout) as client:
            reply = client.evaluate(handle.tab_id, expression, timeout)
            value, err = client.value_of(reply, timeout)
            return Answer(None, err, "js") if err else Answer(value, "", "")
    except rdp.RdpError as e:
        kind = "timeout" if e.kind == "timeout" else "transport"
        return Answer(None, str(e), kind)


def _evaluate_bidi(handle: Handle, expression: str, timeout: float) -> Answer:
    """One JS evaluation over a BiDi session (the flagged fallback channel)."""
    if not handle.tab_id:
        return Answer(None, f"this BiDi handle names no context ({handle.ws_url})", "protocol")
    text, err = bidi.evaluate(bidi.Endpoint(handle.host, handle.port), handle.tab_id, expression, timeout)
    if err:
        return Answer(None, err, "protocol")
    try:
        return Answer(json.loads(text), "", "")
    except (TypeError, ValueError):
        return Answer(text, "", "")


# ── capability refusals (D-4) ────────────────────────────────────────────────


def row_key(row) -> str:
    """A tab row's id, whichever channel's shape it came from ("" when it has none)."""
    return getattr(row, "id", "") or getattr(row, "tab_id", "") or ""


def owner_of(handle: Optional[Handle], rows=None, base_port: int = 9222) -> str:
    """Which registered browser this handle belongs to (id, else "").

    A handle carries the endpoint it came from; the Settings rows say which browser owns
    that endpoint (`base + registry offset`, or a hand-edited port). Only when a handle
    names no known endpoint does the channel decide — the first browser that speaks it.
    """
    if handle is None:
        return ""
    if handle.browser:
        return handle.browser
    from .browsers import browser_for_port, profile_for_protocol
    owner = browser_for_port(handle.port, base_port, rows)
    if owner:
        return owner
    profile = profile_for_protocol(handle.channel)
    return profile.id if profile is not None else ""


def tab_identity(handle: Handle, tab_id: str, timeout: float = DEFAULT_TIMEOUT) -> Tuple[str, str]:
    """(title, url) of one tab on this endpoint — its own channel's listing (D-2)."""
    rows, _err = list_rows(handle, timeout)
    for row in rows:
        if getattr(row, "id", "") == tab_id:
            return getattr(row, "title", "") or "", getattr(row, "url", "") or ""
    return "", ""


CAPABILITY_OPS = (("evaluate", "evaluate"), ("click", "click"), ("connect", "tabs"),
                  ("attach", "tabs"), ("list", "tabs"), ("tabs", "tabs"), ("diagnose", "tabs"),
                  ("probe", "tabs"), ("session", "tabs"), ("prepare", "tabs"))
DOMAIN_OPS = {"runtime": "evaluate", "target": "tabs", "dom": "dom", "input": "input",
              "page": "screenshot", "network": "network", "storage": "storage"}


def capability_for(op: str) -> str:
    """The capability an operation name needs: a CDP method's domain, else its own word."""
    text = str(op or "").strip()
    if "." in text:
        domain = text.split(".")[0].strip().lower()
        return DOMAIN_OPS.get(domain, domain or "unknown")
    low = text.lower()
    for token, capability in CAPABILITY_OPS:
        if token in low:
            return capability
    return "unknown"


def rdp_capabilities() -> frozenset:
    """What the DevTools protocol can do here — read from the registry, never hardcoded."""
    from .browsers import capabilities, profile_for_protocol
    profile = profile_for_protocol(PROTOCOL_RDP)
    return capabilities(profile) if profile is not None else frozenset({"tabs", "evaluate", "click"})


def refusal(handle: Optional[Handle], op: str) -> str:
    """Why this operation cannot run on this channel — "" when it can (D-4/D-8).

    Two different reasons, named as they are: the DevTools protocol has no such domain, and
    the WebDriver BiDi channel is *deliberately* not driven at all (enabling it sets
    `navigator.webdriver=true` — Bug 1719505 — which is the whole point of the stealth one).
    """
    if not is_remote(handle):
        return ""
    if str(handle.channel).lower() == PROTOCOL_BIDI:
        return (f"{PROTOCOL_BIDI.upper()} cannot run {op}: the Remote Agent is detected but not "
                f"driven — enabling it sets navigator.webdriver=true (Bug 1719505). Start Firefox "
                f"with --start-debugger-server and use the rdp channel instead.")
    capability = capability_for(op)
    capabilities = rdp_capabilities()
    if capability in capabilities:
        return ""
    return (f"{str(handle.channel).upper()} cannot run {op}: the DevTools protocol has no "
            f"{capability} support on Firefox — it offers only "
            f"{', '.join(sorted(capabilities))}, and that operation needs a CDP browser "
            f"(Chrome/Edge). Use Runtime.evaluate for click-only work.")


def block(transport, op: str) -> str:
    """The refusal for this transport, remembered on it like any other failure (B8)."""
    reason = refusal(handle_of(transport), op)
    if not reason:
        return ""
    try:
        transport.last_error, transport.last_error_kind = reason, CAPABILITY_KIND
    except Exception:
        pass
    return reason


# ── honest failure classification (D-7) ──────────────────────────────────────


def _http_kind(host: str, port: int, timeout: float) -> str:
    """What the endpoint answers as HTTP: `json` (CDP), `http` (something else), `none`."""
    url = f"http://{host}:{int(port)}/json/version"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=max(0.2, min(timeout, 1.0))) as resp:
            return "json" if resp.status == 200 else "http"
    except urllib.error.HTTPError:
        return "http"          # an HTTP server is there, it is just not Chrome's devtools
    except Exception:
        return "none"


def _other_channel(handle: Handle, timeout: float) -> str:
    """Which channel DOES answer here (so a wrong row can be told apart from a closed port)."""
    wait = max(0.2, min(timeout, GREETING_WAIT))
    if handle.channel != PROTOCOL_RDP and rdp.probe(rdp.Endpoint(handle.host, handle.port), wait):
        return PROTOCOL_RDP
    if handle.channel != PROTOCOL_BIDI and bidi.open_session(
            bidi.Endpoint(handle.host, handle.port), wait):
        return PROTOCOL_BIDI
    return _http_kind(handle.host, handle.port, wait)


def _remote_agent_note(handle: Handle) -> str:
    """The owner's log, explained: Firefox started on the channel that flags the browser."""
    return (f"⚠ Firefox on {handle.host}:{handle.port} answers HTTP but not its DevTools socket — "
            "that is the **Remote Agent** opened by --remote-debugging-port. It sets "
            "navigator.webdriver = true for the whole browser session (Firefox bug 1719505) and its "
            "CDP was removed, which is why /json/list answers 404. Fix: close Firefox, then start it "
            f"with --start-debugger-server {int(handle.port)}, and click Prepare Profile once so the "
            "profile keeps devtools.debugger.remote-enabled=true.")


def explain_failure(handle: Handle, profile, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Why this endpoint could not be listed, and the one action that fixes it (D-7)."""
    label = profile.label if profile is not None else str(handle.channel).upper()
    flag = browsers.debug_arg(profile, handle.port) if profile is not None else ""
    other = _other_channel(handle, timeout)
    if other == PROTOCOL_RDP:
        return (f"⚠ {label} on {handle.host}:{handle.port} answers the Firefox DevTools (RDP) socket, "
                f"but this row speaks {str(handle.channel).upper()}. Fix: set this browser row's "
                f"channel (or start {label} with {flag}).")
    if other == PROTOCOL_BIDI:
        return (f"⚠ {label} on {handle.host}:{handle.port} answers a WebDriver BiDi session "
                f"(the flagged Remote Agent). Fix: start it with {flag} instead, or point this row "
                f"at the browser you meant to drive.")
    if other == "json":
        return (f"⚠ {label} on {handle.host}:{handle.port} answers CDP, but this row speaks "
                f"{str(handle.channel).upper()}. Fix: switch the row's channel to CDP.")
    if other == "http" and handle.channel == PROTOCOL_RDP:
        return _remote_agent_note(handle)
    if other == "http":
        return (f"⚠ {label} on {handle.host}:{handle.port} answers some other tool's HTTP endpoint. "
                f"Fix: start {label} with {flag} on a free port and update the settings row.")
    return (f"⚠ {label} not reachable on {handle.host}:{handle.port} — nothing listens there. "
            f"Fix: start {label} with {flag}" + (f" {protocols.DEFAULT_DEBUGGER_PORT}?" if not flag else ""))


def attach_hint(profile, port) -> str:
    """The one-line "how to open this browser's channel" text (empty for no profile)."""
    return f"{profile.label}: {browsers.debug_arg(profile, port)}" if profile is not None else ""


def scan_line(rows: List[Dict[str, Any]]) -> str:
    """The Settings line: every endpoint this app scans, and which are switched off (D-9)."""
    parts = []
    for row in rows:
        where = f"{row.get('host', '')}:{row['port']}".lstrip(":")
        state = f"{row['id']} {where} ({str(row['protocol']).upper()})"
        parts.append(state if row.get("enabled") else f"{row['id']} — off")
    return "Scanning: " + " · ".join(parts)
