"""One listing seam for every browser (2026-09-22).

The pool, the URL reconciler and the panel all ask the same question — "which
tabs does this browser have open right now?" — and the answer must look the same
whether the browser speaks CDP (Chrome/Edge: one socket per tab) or RDP
(Firefox: debugger server, `browserId` tabs). `list_targets` answers it with
`TargetRef` rows that carry the browser id and the endpoint port, so two
browsers can be listed, joined and pooled in the same pass.

The registry's protocol is tried first and a working answer is trusted for
five minutes, so a steady browser costs one listing per cycle: no probe
round-trips, and — what matters for Firefox — no per-cycle approval prompts.
Only a failure re-measures, through `detect_protocol` (an ESR Firefox with
`remote.active-protocols=2` still answers CDP and keeps the full automation
matrix), and a dead endpoint stays quiet for five seconds before it re-probes.

RULE 18: leaf module; listing is sync (the CDP path already is) and runs in an
executor at the call sites.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import browsers, rdp
from .cdp.tabs import fetch_tabs_sync

CDP = browsers.PROTOCOL_CDP
RDP = browsers.PROTOCOL_RDP

_POS_TTL = 300.0  # a working protocol stays trusted for five minutes
_NEG_TTL = 5.0    # a dead endpoint re-probes next cycle, not next pass

_cache: Dict[Tuple[str, int], Tuple[str, float]] = {}


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


def _attempt(protocol: str, endpoint: rdp.Endpoint, timeout: float,
             browser_id: str) -> Tuple[List[TargetRef], str]:
    """List through one protocol (the directed guess or the fallback winner)."""
    if protocol == CDP:
        return _cdp_refs(endpoint.host, endpoint.port, timeout, browser_id)
    return _rdp_refs(endpoint.host, endpoint.port, timeout, browser_id)


def _unreachable(profile: browsers.BrowserProfile, host: str, port: int) -> str:
    """The composed not-reachable line (one text for the cache and the probe)."""
    return (f"{profile.label} not reachable on {host}:{port} — start it with "
            f"{profile.debug_arg}={port} ({profile.notes.split('.')[0]})")


def _recalled(host: str, port: int) -> Optional[str]:
    """The cached protocol for this endpoint, or None when unknown/expired.

    A recalled miss ("") means a freshly dead endpoint — the caller stays
    quiet instead of re-probing. Races are benign: a stale recall fails the
    directed attempt and self-corrects through the fallback.
    """
    hit = _cache.get((host, int(port)))
    if hit is None:
        return None
    protocol, deadline = hit
    if time.monotonic() >= deadline:
        _cache.pop((host, int(port)), None)
        return None
    return protocol


def _remember(host: str, port: int, protocol: str) -> None:
    """Cache this endpoint's protocol ("" = dead: a short memory, not a grudge)."""
    ttl = _POS_TTL if protocol else _NEG_TTL
    _cache[(host, int(port))] = (protocol, time.monotonic() + ttl)


def reset_protocol_cache() -> None:
    """Forget every endpoint's protocol (tests start here; production never calls)."""
    _cache.clear()


def _list_known(profile: browsers.BrowserProfile, host: str, port: int,
                timeout: float) -> Tuple[List[TargetRef], str]:
    """List one known browser: the directed attempt, then at most one fallback."""
    endpoint = rdp.Endpoint(host, port)
    recalled = _recalled(host, port)
    if recalled == "":
        return [], _unreachable(profile, host, port)
    directed = recalled or profile.protocol
    refs, err = _attempt(directed, endpoint, timeout, profile.id)
    if not err:
        _remember(host, port, directed)
        return refs, ""
    found = detect_protocol(host, port, min(timeout, 1.0))
    if not found:
        _remember(host, port, "")
        return [], _unreachable(profile, host, port)
    if found == directed:
        return refs, err
    refs, err = _attempt(found, endpoint, timeout, profile.id)
    _remember(host, port, found)  # the probe proved it answers; trust that
    return refs, err


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
    return _list_known(profile, host, port_i, timeout)


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
