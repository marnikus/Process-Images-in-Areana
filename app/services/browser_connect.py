"""Browser connect service — read the settings, scan every declared browser.

This is the seam between "what the user configured" and "what protocol we
speak". It turns settings into `BrowserEndpoint`s, scans them all concurrently,
and logs the result naming the **real** browser — the fix for a log that said
"Chrome connection error" while pointing at Firefox on 9224.

Backward compatible by construction: with no `browser_endpoints` configured it
scans the single legacy `cdp_host`/`cdp_port` Chrome endpoint, which is exactly
what the app did before.

Layer: services — composes browser leaves; no Qt, no UI imports.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from ..browser.browser_scan import ScanReport, scan_endpoints
from ..browser.endpoints import FIREFOX, BrowserEndpoint, default_endpoints, parse_endpoints

__all__ = ["endpoints_from_settings", "scan_all", "log_scan_report", "log_firefox_hint"]

_hinted: set = set()  # one prompt hint per Firefox endpoint per app run, not per scan


def _setting(settings: Any, key: str, fallback: Any = None) -> Any:
    """Read a key from a dict-like or attribute-style settings object."""
    if settings is None:
        return fallback
    if isinstance(settings, dict):
        return settings.get(key, fallback)
    return getattr(settings, key, fallback)


def endpoints_from_settings(settings: Any) -> List[BrowserEndpoint]:
    """The declared browsers, or the legacy single Chrome endpoint as fallback.

    An unreadable/empty configuration falls back rather than scanning nothing,
    so an upgrade can never leave the app with no browser at all.
    """
    host = str(_setting(settings, "cdp_host", "127.0.0.1") or "127.0.0.1")
    base = _setting(settings, "browser_base_port", 0)
    rows = _setting(settings, "browser_endpoints", None)
    declared = parse_endpoints(rows if isinstance(rows, list) else [], base=base, host=host)
    if declared:
        return declared
    return default_endpoints(host, _setting(settings, "cdp_port", 0))


async def scan_all(settings: Any, timeout: float = 5.0) -> ScanReport:
    """Scan every declared browser concurrently and return the merged report."""
    return await scan_endpoints(endpoints_from_settings(settings), timeout)


def log_scan_report(report: ScanReport, log: Optional[Callable[..., Any]]) -> None:
    """Log one summary line, then one warning per failing browser, by name."""
    if log is None:
        return
    log(f"🔎 Browser scan — {report.summary()}", "info" if report.any_ok else "warn")
    for message in report.errors:
        log(f"❌ {message}", "error")


def log_firefox_hint(endpoint: BrowserEndpoint, log: Optional[Callable[..., Any]]) -> bool:
    """Explain the "Incoming Connection" dialog — once per endpoint, not per scan.

    Returns whether it printed, so the caller (and the test) can tell the
    difference between "explained" and "already explained".
    """
    from ..browser.rdp.prefs_help import prompt_help_lines
    if log is None or endpoint.kind != FIREFOX or endpoint.key in _hinted:
        return False
    _hinted.add(endpoint.key)
    for line in prompt_help_lines(endpoint.port):
        log(line, "info")
    return True
