"""Deterministic, bounded comparison of two sanitized recording read models."""

from __future__ import annotations

from collections import Counter
import difflib
import re
from typing import Any

MAX_SIGNATURES = 300
MAX_DIFF_LINES = 200


class RecordingComparison:
    """Find common evidence and the first ordered divergence."""

    def compare(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        a = [_signature(row) for row in left.get("events", [])][:MAX_SIGNATURES]
        b = [_signature(row) for row in right.get("events", [])][:MAX_SIGNATURES]
        common = list((Counter(a) & Counter(b)).elements())
        return {
            "left": _identity(left), "right": _identity(right),
            "evidence_complete": bool(left.get("evidence_complete") and right.get("evidence_complete")),
            "warnings": _warnings(left, right),
            "common": common[:50],
            "left_only": list((Counter(a) - Counter(b)).elements())[:50],
            "right_only": list((Counter(b) - Counter(a)).elements())[:50],
            "first_divergence": _first_divergence(a, b),
            "milestones": {"left": _milestones(left), "right": _milestones(right)},
            "dom_diff": _dom_diff(left, right),
        }


def _identity(details: dict[str, Any]) -> dict[str, Any]:
    manifest = details.get("manifest", {})
    keys = ("session_id", "actor_label", "result_label", "method", "outcome", "kind", "url")
    return {key: manifest.get(key, "") for key in keys}


def _signature(event: dict[str, Any]) -> str:
    kind = str(event.get("kind", "unknown"))
    payload = event.get("payload") or {}
    if kind == "mutation":
        changes = payload.get("changes") or []
        parts = [f"{x.get('op')}:{x.get('path')}:{x.get('name', '')}" for x in changes[:5]]
        return f"mutation|{'|'.join(parts)}"
    if kind.startswith("network_"):
        return f"{kind}|{payload.get('category', '')}|{payload.get('method', '')}|{payload.get('url', '')}|{payload.get('status', '')}|{payload.get('error', '')}"
    if kind in ("state", "solve_report"):
        acceptance = payload.get("acceptance") or {}
        return f"{kind}|{payload.get('state', payload.get('status', ''))}|{payload.get('outcome', '')}|{payload.get('method', '')}|{acceptance.get('state', '')}"
    return kind


def _first_divergence(left: list[str], right: list[str]) -> dict[str, Any]:
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            return {"operation": tag, "left_index": i1, "right_index": j1,
                    "left": left[i1:i2][:5], "right": right[j1:j2][:5]}
    return {}


def _milestones(details: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for event in details.get("events", []):
        payload = event.get("payload") or {}
        if event.get("kind") in ("state", "solve_report"):
            state = payload.get("state") or payload.get("status") or event.get("kind")
            rows.append({"state": state, "offset_ms": event.get("offset_ms", 0),
                         "outcome": payload.get("outcome", ""), "method": payload.get("method", "")})
    return rows[:50]


def _warnings(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    warnings = []
    for side, details in (("left", left), ("right", right)):
        manifest = details.get("manifest", {})
        if manifest.get("truncated"):
            warnings.append(f"{side} evidence truncated: {', '.join(manifest['truncated'])}")
        if manifest.get("result_label", "unknown") == "unknown":
            warnings.append(f"{side} result label is unknown")
        if manifest.get("actor_label", "unknown") == "unknown":
            warnings.append(f"{side} actor label is unknown")
    return warnings


def _dom_diff(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    a = _html_lines(left)
    b = _html_lines(right)
    diff = difflib.unified_diff(a, b, fromfile="left", tofile="right", lineterm="")
    return list(diff)[:MAX_DIFF_LINES]


def _html_lines(details: dict[str, Any]) -> list[str]:
    snapshot = details.get("latest_snapshot") or {}
    html = str(snapshot.get("html", ""))
    return [line.strip() for line in re.sub(r"><", ">\n<", html).splitlines() if line.strip()]
