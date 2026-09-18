"""Diff + timeline comparison for two recordings (manual vs bot research).

Pure functions: bounded unified-diff hunks between two snapshots and an
event-timeline summary per session. The UI renders the result; no I/O here.
"""

from __future__ import annotations

import difflib
from typing import Any, Dict, List

MAX_HUNK_LINES = 400  # bound the payload the WebChannel carries


def snapshot_diff(html_a: str, html_b: str, context: int = 1) -> Dict[str, Any]:
    """Bounded unified diff between two snapshots."""
    a = (html_a or "").splitlines()
    b = (html_b or "").splitlines()
    lines = list(difflib.unified_diff(a, b, "snapshot A", "snapshot B",
                                      lineterm="", n=max(0, min(context, 3))))
    truncated = len(lines) > MAX_HUNK_LINES
    return {"lines": lines[:MAX_HUNK_LINES], "total": len(lines),
            "truncated": truncated,
            "identical": not any(l.startswith(("+", "-")) and not l.startswith(("+++", "---"))
                                 for l in lines[:MAX_HUNK_LINES])}


def timeline_summary(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts by kind + per-minute rates + network families (bounded)."""
    counts, minutes, hosts = _accumulate(events or [])
    first = str(events[0].get("ts") or "") if events else ""
    last = str(events[-1].get("ts") or "") if events else ""
    top_hosts = sorted(hosts.items(), key=lambda kv: -kv[1])[:20]
    return {"total": len(events or []), "by_kind": counts,
            "by_minute": dict(sorted(minutes.items())[:60]),
            "network_hosts": dict(top_hosts),
            "first_ts": first, "last_ts": last}


def _accumulate(events: List[Dict[str, Any]]):
    counts: Dict[str, int] = {}
    minutes: Dict[str, int] = {}
    hosts: Dict[str, int] = {}
    for evt in events:
        _count_event(evt, counts, minutes, hosts)
    return counts, minutes, hosts


def _count_event(evt: Dict[str, Any], counts: Dict[str, int],
                 minutes: Dict[str, int], hosts: Dict[str, int]) -> None:
    kind = str(evt.get("kind") or "?")
    counts[kind] = counts.get(kind, 0) + 1
    ts = str(evt.get("ts") or "")[:16]  # minute bucket YYYY-MM-DDTHH:MM
    if ts:
        minutes[ts] = minutes.get(ts, 0) + 1
    if kind == "network":
        host = str(evt.get("host") or "?")[:40]
        hosts[host] = hosts.get(host, 0) + 1
