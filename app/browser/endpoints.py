"""One listing seam for every browser (2026-09-21).

The pool, the URL reconciler and the panel all ask the same question — "which
tabs does this browser have open right now?" — and the answer must look the same
whether the browser speaks CDP (Chrome/Edge: one socket per tab), the Firefox
DevTools RDP socket (one socket for the whole browser, tabs are handles), or
WebDriver BiDi (the Remote Agent's session). `list_targets` answers it with
`TargetRef` rows that carry the browser id, the endpoint host/port and the
protocol, so two browsers can be listed, joined and pooled in the same pass.

`detect_protocol` probes the endpoint instead of trusting the registry, in the
order CDP → RDP → BiDi: an ESR Firefox launch that still answers CDP keeps the
full automation matrix, an ordinary Firefox answers the DevTools greeting, and a
`--remote-debugging-port` Firefox answers `POST /session` — reachable, but a
flagged session the panel says so about.

`evaluate` and `click` are dispatched the same way, and a protocol that cannot do
the operation answers with the reason **naming the protocol** — never a timeout
(D-3/D-7).

RULE 18: leaf module; listing is sync (the CDP path already is) and runs in an
executor at the call sites.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import bidi, browsers, rdp
from .cdp.tabs import fetch_tabs_sync

CDP = browsers.PROTOCOL_CDP
RDP = browsers.PROTOCOL_RDP
BIDI = browsers.PROTOCOL_BIDI
DETECT_TIMEOUT = 1.0


@dataclass(frozen=True)
class TargetRef:
    """One browser tab, whatever protocol listed it.

    Carries everything an action needs (host, port, protocol, browser, tab id), so
    `evaluate`/`click` take a ref instead of six loose parameters.
    """

    id: str
    title: str
    url: str
    ws_url: str
    browser: str = "chrome"
    port: int = 9222
    protocol: str = CDP
    host: str = "127.0.0.1"


def _get_json(url: str, timeout: float) -> Optional[dict]:
    """GET JSON from a debug endpoint; None on any failure (never raises)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None


def detect_protocol(host: str, port: int, timeout: float = DETECT_TIMEOUT) -> str:
    """`cdp` / `rdp` / `bidi` / `''` — what this endpoint answers, in that order."""
    try:
        version = _get_json(f"http://{host}:{int(port)}/json/version", timeout)
        if isinstance(version, dict) and version:
            return CDP
    except Exception:
        pass
    if rdp.probe(rdp.Endpoint(host, int(port)), min(timeout, DETECT_TIMEOUT)):
        return RDP
    return BIDI if bidi.open_session(bidi.Endpoint(host, int(port)), timeout) else ""


def _cdp_refs(host: str, port: int, timeout: float, browser_id: str) -> Tuple[List[TargetRef], str]:
    """CDP listing through the existing tab fetcher (unchanged behaviour)."""
    tabs, err, _tried = fetch_tabs_sync(host, port, timeout)
    refs = [TargetRef(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url,
                      browser=browser_id, port=int(port), protocol=CDP, host=host)
            for t in tabs if t.id or t.ws_url]
    return refs, ("" if refs else (err or "no tabs listed"))


def _rdp_refs(host: str, port: int, timeout: float, browser_id: str) -> Tuple[List[TargetRef], str]:
    """RDP listing: one socket for the browser, each tab a stable `ctx-N` handle."""
    rows, err = rdp.list_targets(rdp.Endpoint(host, int(port)), timeout)
    refs = [TargetRef(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url, browser=browser_id,
                      port=int(port), protocol=RDP, host=host) for t in rows]
    return refs, ("" if refs else (err or "no tabs listed"))


def _bidi_refs(host: str, port: int, timeout: float, browser_id: str) -> Tuple[List[TargetRef], str]:
    """BiDi listing: the session socket is shared, the tab id is the context id."""
    rows, err = bidi.list_contexts(bidi.Endpoint(host, int(port)), timeout)
    ws_url = f"ws://{host}:{int(port)}{bidi.SESSION_PATH}"
    refs = [TargetRef(id=r["id"], title=r.get("title") or r.get("url", ""), url=r.get("url", ""),
                      ws_url=ws_url, browser=browser_id, port=int(port), protocol=BIDI, host=host)
            for r in rows or []]
    return refs, ("" if refs else (err or "no tabs listed"))


def list_targets(browser_id: str, host: str, port, timeout: float = 3.0) -> Tuple[List[TargetRef], str]:
    """Every tab of one browser, or ([] + the reason) — the pool's one entry point.

    An unknown browser id is refused by name (the panel shows the message); a
    reachable endpoint that answers neither protocol reports that too.
    """
    profile = browsers.profile_of(browser_id)
    if profile is None:
        return [], f"unknown browser '{browser_id}' — registered: {', '.join(browsers.profile_ids())}"
    try:
        port_i = int(port)
    except Exception:
        return [], f"invalid port for {browser_id}: {port!r}"
    protocol = detect_protocol(host, port_i, min(timeout, DETECT_TIMEOUT))
    if protocol == CDP:
        return _cdp_refs(host, port_i, timeout, profile.id)
    if protocol == RDP:
        return _rdp_refs(host, port_i, timeout, profile.id)
    if protocol == BIDI:
        return _bidi_refs(host, port_i, timeout, profile.id)
    return [], _unreachable(profile, host, port_i)


def _unreachable(profile, host: str, port: int) -> str:
    """What to say when a browser is not answering — with the flag that opens it."""
    hint = browsers.debug_arg(profile, port).replace("--", "", 1)
    return (f"{profile.label} not reachable on {host}:{port} — start it with {hint} "
            f"({profile.notes.split('.')[0]})")


def _named_refusal(protocol: str, op: str, why: str) -> Tuple[None, str]:
    """`(None, reason)` for an operation this protocol cannot do (never a timeout)."""
    return None, f"{protocol.upper()} cannot {op} here — {why}"


def evaluate(ref: TargetRef, expression: str, timeout: float = 3.0) -> Tuple[Optional[str], str]:
    """Evaluate JS in one listed tab, whatever protocol listed it.

    RDP answers the parsed value, which is re-serialized so every protocol hands
    the caller the same thing: a JSON text (or None and the reason).
    """
    if ref.protocol == RDP:
        value, err = rdp.evaluate_json(rdp.Endpoint(ref.host, int(ref.port)), ref.id, expression, timeout)
        return (None, err) if err else (json.dumps(value), "")
    if ref.protocol == BIDI:
        return bidi.evaluate(bidi.Endpoint(ref.host, int(ref.port)), ref.id, expression, timeout)
    return _named_refusal(CDP, "evaluate", "the connected CDP client owns the tab socket (see the pool)")


def click(ref: TargetRef, selector: str, timeout: float = 3.0) -> Tuple[bool, str]:
    """Click one element by CSS selector — RDP only, and named otherwise.

    RDP has no input synthesis, so a click is `el.click()` inside the page. It
    cannot exist for CDP/BiDi at this seam because both own their tab socket
    elsewhere; saying which is the point (D-7).
    """
    if ref.protocol == RDP:
        return rdp.click(rdp.Endpoint(ref.host, int(ref.port)), ref.id, selector, timeout)
    if ref.protocol == BIDI:
        return False, "BIDI cannot click here — the Remote Agent exposes no input primitive (and it flags the browser)"
    return False, "CDP clicks run through the connected CDP client (see the pool), not this listing seam"


def enabled_targets(settings, host: str, timeout: float = 3.0) -> Tuple[List[TargetRef], List[str]]:
    """List every enabled browser's tabs at once (the reconciler's multi-browser call).

    `settings` is the per-browser map (`{id: {enabled, port}}`); each browser is
    asked at its own resolved endpoint and one browser being down never hides the
    other's tabs. Returns (targets, one error line per browser that failed).
    """
    refs: List[TargetRef] = []
    errors: List[str] = []
    for profile in browsers.PROFILES:
        entry = (settings or {}).get(profile.id) or {}
        if entry.get("enabled") is False:
            continue
        got, err = list_targets(profile.id, host, entry.get("port") or profile.port_offset, timeout)
        refs.extend(got)
        if err:
            errors.append(f"{profile.id}: {err}")
    return refs, errors
