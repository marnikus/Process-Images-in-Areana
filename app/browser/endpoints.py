"""One listing seam for every browser (2026-09-21).

The pool, the URL reconciler and the panel all ask the same question — "which
tabs does this browser have open right now?" — and the answer must look the same
whether the browser speaks CDP (Chrome/Edge: one socket per tab) or RDP
(Firefox: debugger server, `browserId` tabs). `list_targets` answers it with
`TargetRef` rows that carry the browser id and the endpoint port, so two
browsers can be listed, joined and pooled in the same pass.

`detect_protocol` probes the endpoint instead of trusting the registry: an ESR
Firefox launch with `remote.active-protocols=2` answers CDP and therefore keeps
the full automation matrix, while a modern Firefox is driven over RDP.

RULE 18: leaf module; listing is sync (the CDP path already is) and runs in an
executor at the call sites.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import browsers, rdp
from .cdp.tabs import fetch_tabs_sync

CDP = browsers.PROTOCOL_CDP
RDP = browsers.PROTOCOL_RDP


@dataclass(frozen=True)
class TargetRef:
    """One browser tab, whatever protocol listed it."""

    id: str
    title: str
    url: str
    ws_url: str
    browser: str = "chrome"
    port: int = 9222
    protocol: str = CDP


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


def detect_protocol(host: str, port: int, timeout: float = 1.0) -> str:
    """`cdp` / `rdp` / `''` — what this endpoint answers (CDP wins when both do)."""
    try:
        version = _get_json(f"http://{host}:{int(port)}/json/version", timeout)
        if isinstance(version, dict) and version:
            return CDP
    except Exception:
        pass
    return RDP if rdp.probe(rdp.Endpoint(host, int(port)), timeout) else ""


def _cdp_refs(host: str, port: int, timeout: float, browser_id: str) -> Tuple[List[TargetRef], str]:
    """CDP listing through the existing tab fetcher (unchanged behaviour)."""
    tabs, err, _tried = fetch_tabs_sync(host, port, timeout)
    refs = [TargetRef(id=t.id, title=t.title, url=t.url, ws_url=t.ws_url,
                      browser=browser_id, port=int(port), protocol=CDP)
            for t in tabs if t.id or t.ws_url]
    return refs, ("" if refs else (err or "no tabs listed"))


def _rdp_refs(host: str, port: int, timeout: float, browser_id: str) -> Tuple[List[TargetRef], str]:
    """RDP listing: one `rdp://host:port#id` handle per tab (endpoint = text before `#`)."""
    rows, err = rdp.list_tabs(rdp.Endpoint(host, int(port)), timeout)
    refs = [TargetRef(id=r["id"], title=r.get("title") or r.get("url", ""), url=r.get("url", ""),
                      ws_url=f"rdp://{host}:{int(port)}#{r['id']}",
                      browser=browser_id, port=int(port), protocol=RDP)
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
    protocol = detect_protocol(host, port_i, min(timeout, 1.0))
    if protocol == CDP:
        return _cdp_refs(host, port_i, timeout, profile.id)
    if protocol == RDP:
        return _rdp_refs(host, port_i, timeout, profile.id)
    return [], (f"{profile.label} not reachable on {host}:{port_i} — start it with "
                f"{profile.debug_arg}={port_i} ({profile.notes.split('.')[0]})")


def enabled_targets(settings, host: str, base=9222, timeout: float = 3.0) -> Tuple[List[TargetRef], List[str]]:
    """List every enabled browser's tabs at once (the reconciler's multi-browser call).

    `settings` is the per-browser map (`{id: {enabled, port}}`); each browser is
    asked at its own resolved endpoint (`base + offset`, hand-set `port` wins)
    and one browser being down never hides the other's tabs. Returns (targets,
    one error line per browser that failed).
    """
    refs: List[TargetRef] = []
    errors: List[str] = []
    for profile in browsers.PROFILES:
        entry = (settings or {}).get(profile.id) or {}
        if entry.get("enabled") is False:
            continue
        port = browsers.resolve_port(base, profile, entry.get("port"))
        got, err = list_targets(profile.id, host, port, timeout)
        refs.extend(got)
        if err:
            errors.append(f"{profile.id}: {err}")
    return refs, errors
