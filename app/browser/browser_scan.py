"""Multi-browser scan — every declared endpoint, each on its own protocol.

The bug this module exists to kill: one hard-wired Chrome endpoint meant the
app asked Firefox for `http://…/json/list`, got `Not Found`, retried forever,
and reported it as a "Chrome connection error" while pointing at Firefox.

So the scan is per endpoint, and the protocol is chosen from the endpoint's
**declared** kind (`browser/endpoints.py`) rather than sniffed:

* ``chrome``  → CDP `/json/list`
* ``firefox`` → RDP over a raw socket (`browser/rdp/discovery.py`)

One endpoint failing never cancels the others — a dead Firefox must not hide a
working Chrome — and every failure is reported against the **real** browser
name, which is what makes the log readable again.

Layer: browser — composes the two protocol leaves; no Qt, no services, no UI.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .endpoints import CHROME, FIREFOX, BrowserEndpoint, endpoint_label

log = logging.getLogger("arena")

__all__ = ["EndpointResult", "ScanReport", "scan_endpoint", "scan_endpoints", "SCANNERS"]


@dataclass(frozen=True)
class EndpointResult:
    """What one endpoint answered: its tabs, or why it could not be read."""

    endpoint: BrowserEndpoint
    tabs: List[Any] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        """Answered without error — including a real browser holding no tabs."""
        return not self.error

    @property
    def label(self) -> str:
        return endpoint_label(self.endpoint)


@dataclass(frozen=True)
class ScanReport:
    """Every endpoint's outcome, plus the merged tab list the pool consumes."""

    results: List[EndpointResult] = field(default_factory=list)

    @property
    def tabs(self) -> List[Any]:
        return [tab for result in self.results for tab in result.tabs]

    @property
    def errors(self) -> List[str]:
        """`Firefox 127.0.0.1:9224: …` per failure — named, never "Chrome"."""
        return [f"{r.label}: {r.error}" for r in self.results if r.error]

    @property
    def any_ok(self) -> bool:
        return any(r.ok for r in self.results)

    def summary(self) -> str:
        """One log line: which browsers answered, with how many tabs."""
        if not self.results:
            return "no browser endpoints configured"
        parts = [f"{r.label} {len(r.tabs)} tab(s)" if r.ok else f"{r.label} ✗" for r in self.results]
        return " · ".join(parts)


async def _scan_chrome(endpoint: BrowserEndpoint, timeout: float) -> List[Any]:
    """Chrome/Chromium over CDP — the existing `/json/list` path."""
    from .cdp.tabs import fetch_tabs_sync
    loop = asyncio.get_event_loop()
    tabs, err, _tried = await loop.run_in_executor(
        None, lambda: fetch_tabs_sync(endpoint.host, endpoint.port, timeout))
    if err and not tabs:
        raise ConnectionError(err)
    return list(tabs)


async def _scan_firefox(endpoint: BrowserEndpoint, timeout: float) -> List[Any]:
    """Firefox over the DevTools RDP — no HTTP, no WebSocket."""
    from .rdp.discovery import list_firefox_tabs
    return await list_firefox_tabs(endpoint.host, endpoint.port, timeout)

# Declared kind → scanner. A kind with no scanner is reported, never guessed at.
SCANNERS: Dict[str, Callable[[BrowserEndpoint, float], Any]] = {
    CHROME: _scan_chrome,
    FIREFOX: _scan_firefox,
}


async def scan_endpoint(endpoint: BrowserEndpoint, timeout: float = 5.0) -> EndpointResult:
    """Read one endpoint with its own protocol; failure is data, not an exception."""
    scanner = SCANNERS.get(endpoint.kind)
    if scanner is None:
        return EndpointResult(endpoint=endpoint, error=f"unknown browser kind '{endpoint.kind}'")
    try:
        tabs = await scanner(endpoint, timeout)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # every protocol failure mode, named per endpoint
        log.debug("scan %s failed: %s", endpoint.key, exc)
        return EndpointResult(endpoint=endpoint, error=_reason(endpoint, exc))
    return EndpointResult(endpoint=endpoint, tabs=list(tabs))


def _reason(endpoint: BrowserEndpoint, exc: Exception) -> str:
    """A message that names the browser and the flag that actually starts it."""
    text = str(exc) or exc.__class__.__name__
    if endpoint.kind == FIREFOX and _looks_unreachable(text):
        return (f"{text} — start it with: firefox.exe "
                f"--start-debugger-server {endpoint.port}")
    return text


def _looks_unreachable(text: str) -> bool:
    """A connection-level failure (port shut) rather than a protocol answer."""
    lowered = text.lower()
    return any(hint in lowered for hint in ("refused", "not open", "timed out",
                                            "timeout", "unreachable", "reset"))


async def scan_endpoints(endpoints: List[BrowserEndpoint],
                         timeout: float = 5.0) -> ScanReport:
    """Scan every endpoint concurrently — one dead browser never hides another."""
    if not endpoints:
        return ScanReport(results=[])
    results = await asyncio.gather(*(scan_endpoint(e, timeout) for e in endpoints))
    return ScanReport(results=list(results))
