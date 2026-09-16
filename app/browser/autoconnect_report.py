"""Auto-connect reporting — pure formatting of one scan/link pass (RULE 2, RULE 4).

Kept out of the service so the wording of "empty" vs "broken" vs "linked" can be
tested without an event loop.
"""

from __future__ import annotations

from typing import Any, Dict, List


def summarize_scan(report: Dict[str, Any]) -> tuple[str, str]:
    """Return ``(message, level)`` for one scan report."""
    endpoint = report.get("endpoint", "")
    if report.get("error"):
        return f"⚠ Auto-connect scan failed on {endpoint}: {report['error']}", "warn"
    if not report.get("matched"):
        return _empty_message(report, endpoint), "warn"
    return _linked_message(report, endpoint), "info"


def _empty_message(report: Dict[str, Any], endpoint: str) -> str:
    pats = ", ".join(report.get("patterns") or ()) or "(empty pattern)"
    return (
        f"🔎 Auto-connect {endpoint}: {report.get('scanned', 0)} page(s), "
        f"0 matched pattern {pats} — nothing to connect"
    )


def _linked_message(report: Dict[str, Any], endpoint: str) -> str:
    extra = _linked_extra(report)
    return (
        f"🔎 Auto-connect {endpoint}: {report.get('scanned', 0)} page(s), "
        f"{report.get('matched', 0)} matched, +{report.get('connected_now', 0)} connected, "
        f"{report.get('pool_total', 0)} in pool{extra}"
    )


def _linked_extra(report: Dict[str, Any]) -> str:
    bits: List[str] = []
    if report.get("duplicates"):
        bits.append(f"{report['duplicates']} duplicate id(s) collapsed")
    if report.get("removed"):
        bits.append(f"{len(report['removed'])} removed")
    if report.get("failed"):
        bits.append(f"{len(report['failed'])} failed")
    return (" — " + ", ".join(bits)) if bits else ""


def startup_message(config) -> str:
    """One-line description of the active auto-connect configuration."""
    pats = ", ".join(getattr(config, "patterns", []) or ()) or "(empty pattern)"
    seconds = max(1, int(getattr(config, "interval_ms", 5000)) // 1000)
    return (
        f"🤖 Auto-connect ON — scanning {getattr(config, 'endpoint', '')} every {seconds}s "
        f"for pages matching “{pats}”"
    )
