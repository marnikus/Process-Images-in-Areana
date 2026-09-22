"""Browser endpoints — the declared (host, port, kind) list the app scans.

One app now talks to several browsers at once, each on its own port. The
settings hold a *declared* kind per port rather than a guess, because the two
protocols are not interchangeable and probing the wrong one is what produced
the `/json/list … Not Found` retry loop:

* ``chrome`` — CDP: HTTP ``/json/list`` for tabs, then a WebSocket per tab.
* ``firefox`` — DevTools RDP: a raw TCP socket speaking length-prefixed JSON.
  Firefox serves **no** HTTP and **no** WebSocket on this port, so a `ws://`
  URL for it is meaningless (see `browser/rdp/`).

Ports derive from one base (9223 → 9223, 9224, 9225…) so a user only sets the
base and a kind per slot, but an explicit port always wins.

Layer: browser leaf — pure data and parsing; no sockets, no Qt, no app imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

__all__ = ["BrowserEndpoint", "CHROME", "FIREFOX", "KINDS", "parse_endpoints",
           "derive_ports", "endpoint_label", "default_endpoints"]

CHROME = "chrome"
FIREFOX = "firefox"
KINDS = (CHROME, FIREFOX)

_LABELS = {CHROME: "Chrome", FIREFOX: "Firefox"}
_MIN_PORT, _MAX_PORT = 1, 65535


@dataclass(frozen=True)
class BrowserEndpoint:
    """One browser to scan: where it listens and which protocol it speaks."""

    host: str
    port: int
    kind: str

    @property
    def label(self) -> str:
        """Display name of the browser — never the word "Chrome" for Firefox."""
        return _LABELS.get(self.kind, self.kind.title())

    @property
    def key(self) -> str:
        """Stable identity of this endpoint (`firefox@127.0.0.1:9224`)."""
        return f"{self.kind}@{self.host}:{self.port}"

    @property
    def speaks_cdp(self) -> bool:
        """True when `/json/list` + WebSocket apply; False for Firefox RDP."""
        return self.kind == CHROME


def _valid_port(value: Any) -> int:
    """A usable TCP port, or 0 when the value is unusable (never a guess)."""
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 0
    return port if _MIN_PORT <= port <= _MAX_PORT else 0


def _valid_kind(value: Any) -> str:
    """A known protocol kind, or '' when unrecognised."""
    kind = str(value or "").strip().lower()
    return kind if kind in KINDS else ""


def derive_ports(base: Any, count: Any) -> List[int]:
    """`9223, 3` → `[9223, 9224, 9225]`; an unusable base yields []."""
    start = _valid_port(base)
    try:
        how_many = int(count)
    except (TypeError, ValueError):
        return []
    if not start or how_many <= 0:
        return []
    return [p for p in (start + i for i in range(how_many)) if _valid_port(p)]


def _one_endpoint(raw: Dict[str, Any], base: Any, index: int, host: str) -> BrowserEndpoint | None:
    """Build one endpoint from a settings row; None when it is unusable."""
    kind = _valid_kind(raw.get("kind"))
    if not kind:
        return None
    port = _valid_port(raw.get("port")) or _nth_port(base, index)
    if not port:
        return None
    return BrowserEndpoint(host=str(raw.get("host") or host).strip() or host,
                           port=port, kind=kind)


def _nth_port(base: Any, index: int) -> int:
    """The index-th port after `base` (the derive rule, for a row with no port)."""
    start = _valid_port(base)
    return _valid_port(start + index) if start else 0


def parse_endpoints(rows: Iterable[Dict[str, Any]], base: Any = 0,
                    host: str = "127.0.0.1") -> List[BrowserEndpoint]:
    """Settings rows → endpoints, unusable rows dropped and duplicates collapsed.

    An empty result means nothing was configured — the caller must say so
    rather than silently scanning a default port (RULE 4).
    """
    seen: Dict[str, BrowserEndpoint] = {}
    for index, raw in enumerate(rows or []):
        if not isinstance(raw, dict):
            continue
        endpoint = _one_endpoint(raw, base, index, host)
        if endpoint is not None:
            seen.setdefault(f"{endpoint.host}:{endpoint.port}", endpoint)
    return list(seen.values())


def default_endpoints(host: str, port: Any) -> List[BrowserEndpoint]:
    """The legacy single-Chrome setup, as a one-entry endpoint list."""
    valid = _valid_port(port)
    return [BrowserEndpoint(host=host or "127.0.0.1", port=valid, kind=CHROME)] if valid else []


def endpoint_label(endpoint: BrowserEndpoint) -> str:
    """`Firefox 127.0.0.1:9224` — for log lines that must name the real browser."""
    return f"{endpoint.label} {endpoint.host}:{endpoint.port}"
