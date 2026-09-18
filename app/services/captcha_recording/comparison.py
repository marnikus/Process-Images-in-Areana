"""Deterministic, bounded comparison of two sanitized recording read models.

The report answers the diagnostic's step 3–5 directly: align the named edges,
name the first real divergence (provider-only and human-timing phases are
expected differences, never divergences), then show the aligned DOM diff, the
network class diff and a validity verdict for the label pair.
"""

from __future__ import annotations

from collections import Counter
import difflib
import re
from typing import Any

from . import milestones
from .reader import LEGACY_STATE_PHASES

MAX_SIGNATURES = 300
MAX_DIFF_LINES = 200
MAX_CLASS_ROWS = 12
OFFSET_TOLERANCE_MS = 1_500
#: Presence mismatches here are structural, not divergences.
_STRUCTURAL_PHASES = frozenset(milestones.PROVIDER_PHASES) | {
    "session_end", "job_result", "dialog_cleared", "acceptance_candidate",
}
_PHASE_ORDER = {phase: index for index, phase in enumerate(milestones.PHASES)}


class RecordingComparison:
    """Find common evidence and the first ordered divergence."""

    def compare(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        a = [_signature(row) for row in left.get("events", [])][:MAX_SIGNATURES]
        b = [_signature(row) for row in right.get("events", [])][:MAX_SIGNATURES]
        alignment = _alignment(left, right)
        return {
            "left": _identity(left), "right": _identity(right),
            "verdict": _verdict(left, right),
            "evidence_complete": bool(left.get("evidence_complete") and right.get("evidence_complete")),
            "warnings": _warnings(left, right),
            "alignment": alignment,
            "first_divergence": _first_divergence(alignment),
            "timing_gaps": _timing_gaps(alignment),
            "common": list((Counter(a) & Counter(b)).elements())[:50],
            "left_only": list((Counter(a) - Counter(b)).elements())[:50],
            "right_only": list((Counter(b) - Counter(a)).elements())[:50],
            "sequence_divergence": _sequence_divergence(a, b),
            "milestones": {"left": left.get("milestones", []), "right": right.get("milestones", [])},
            "network": _network_diff(left, right),
            "dom_diff": _dom_diff(left, right),
        }


def _identity(details: dict[str, Any]) -> dict[str, Any]:
    manifest = details.get("manifest", {})
    keys = ("session_id", "actor_label", "result_label", "method", "outcome",
            "acceptance", "verified", "job", "kind", "url")
    return {key: manifest.get(key, "") for key in keys}


def _phase_offsets(details: dict[str, Any]) -> dict[str, int]:
    """Named edges from the read model, or mapped from legacy `state` rows."""
    offsets = _first_offsets(_milestone_pairs(details.get("milestones") or []))
    for phase, offset in _first_offsets(_legacy_pairs(details.get("events") or [])).items():
        offsets.setdefault(phase, offset)
    return offsets


def _milestone_pairs(rows: list[dict[str, Any]]):
    for row in rows:
        yield str(row.get("phase", "")), row.get("offset_ms")


def _legacy_pairs(events: list[dict[str, Any]]):
    for event in events:
        payload = event.get("payload") or {}
        yield LEGACY_STATE_PHASES.get(str(payload.get("state", "")), ""), event.get("offset_ms")


def _first_offsets(pairs) -> dict[str, int]:
    """Keep the earliest offset per named edge (duplicate stamps are noise)."""
    offsets: dict[str, int] = {}
    for phase, offset_ms in pairs:
        if phase and phase not in offsets:
            offsets[phase] = int(offset_ms or 0)
    return offsets


def _alignment(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    a, b = _phase_offsets(left), _phase_offsets(right)
    order = sorted(set(a) | set(b), key=lambda phase: (_PHASE_ORDER.get(phase, 99), phase))
    rows = []
    for phase in order:
        a_ms, b_ms = a.get(phase), b.get(phase)
        status = "both"
        if a_ms is None:
            status = "b_only"
        elif b_ms is None:
            status = "a_only"
        elif abs(a_ms - b_ms) > OFFSET_TOLERANCE_MS:
            status = "offset"
        rows.append({"phase": phase, "a_ms": a_ms, "b_ms": b_ms, "status": status,
                     "delta_ms": (a_ms - b_ms) if a_ms is not None and b_ms is not None else None,
                     "structural": phase in _STRUCTURAL_PHASES})
    return rows[:80]


def _first_divergence(alignment: list[dict[str, Any]]) -> dict[str, Any]:
    for row in alignment:
        if row["status"] != "both" and not row["structural"]:
            return {"phase": row["phase"], "status": row["status"],
                    "a_ms": row["a_ms"], "b_ms": row["b_ms"], "delta_ms": row["delta_ms"],
                    "why": _why(row)}
    return {}


def _why(row: dict[str, Any]) -> str:
    if row["status"] == "a_only":
        return "present in A, absent in B"
    if row["status"] == "b_only":
        return "present in B, absent in A"
    return f"same edge, {abs(int(row['delta_ms'] or 0))}ms apart"


def _timing_gaps(alignment: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [row for row in alignment if row["delta_ms"] is not None and row["status"] == "offset"]
    rows.sort(key=lambda row: abs(int(row["delta_ms"])), reverse=True)
    return [{"phase": row["phase"], "delta_ms": row["delta_ms"]} for row in rows[:5]]


def _verdict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    actors = [_label(left, "actor_label"), _label(right, "actor_label")]
    results = [_label(left, "result_label"), _label(right, "result_label")]
    if "mixed" in actors:
        return {"comparable": False, "reason": "a mixed bot→manual session is in the pair (analyze the fallback explicitly)"}
    if "unknown" in actors:
        return {"comparable": False, "reason": "label both sessions as bot or manual first"}
    if "unknown" in results:
        return {"comparable": False, "reason": "set the passed/failed result label on both sessions"}
    if len(set(actors)) == 1:
        return {"comparable": True, "reason": f"same actor ({actors[0]}) — use a manual/bot pair for success-signal analysis"}
    return {"comparable": True, "reason": f"{actors[0]} vs {actors[1]} with independent result labels"}


def _label(details: dict[str, Any], key: str) -> str:
    return str((details.get("manifest") or {}).get(key) or "unknown")


def _signature(event: dict[str, Any]) -> str:
    kind = str(event.get("kind", "unknown"))
    payload = event.get("payload") or {}
    if kind == "milestone":
        return f"milestone|{payload.get('phase', '')}"
    if kind == "mutation":
        return f"mutation|{'|'.join(_change_key(item) for item in (payload.get('changes') or [])[:5])}"
    if kind.startswith("network_"):
        return f"{kind}|{payload.get('category', '')}|{payload.get('method', '')}|{payload.get('url', '')}"
    if kind == "state":
        return f"state|{payload.get('state', payload.get('outcome', ''))}"
    return kind


def _change_key(change: dict[str, Any]) -> str:
    if not isinstance(change, dict):
        return str(change)[:40]
    return f"{change.get('op')}:{change.get('path')}:{change.get('name', '')}"


def _sequence_divergence(a: list[str], b: list[str]) -> dict[str, Any]:
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            return {"operation": tag, "a_index": i1, "b_index": j1,
                    "a": a[i1:i2][:5], "b": b[j1:j2][:5]}
    return {}


def _network_diff(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    a = {row["class"]: row["count"] for row in (left.get("network_summary") or [])}
    b = {row["class"]: row["count"] for row in (right.get("network_summary") or [])}
    return {"left": (left.get("network_summary") or [])[:MAX_CLASS_ROWS],
            "right": (right.get("network_summary") or [])[:MAX_CLASS_ROWS],
            "a_only": sorted(set(a) - set(b))[:MAX_CLASS_ROWS],
            "b_only": sorted(set(b) - set(a))[:MAX_CLASS_ROWS],
            "count_delta": sorted((key for key in set(a) & set(b) if a[key] != b[key]),
                                  key=lambda key: -abs(a[key] - b[key]))[:MAX_CLASS_ROWS]}


def _dom_diff(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    diff = difflib.unified_diff(_html_lines(left), _html_lines(right),
                                fromfile="left", tofile="right", lineterm="")
    return list(diff)[:MAX_DIFF_LINES]


def _html_lines(details: dict[str, Any]) -> list[str]:
    snapshot = _aligned_snapshot(details)
    html = str(snapshot.get("html", ""))
    return [line.strip() for line in re.sub(r"><", ">\n<", html).splitlines() if line.strip()]


def _aligned_snapshot(details: dict[str, Any]) -> dict[str, Any]:
    """Compare like for like: the resolved checkpoint, else the last one."""
    snapshots = details.get("snapshots") or []
    if not snapshots:
        return details.get("latest_snapshot") or {}
    resolved = [row for row in snapshots if row.get("reason") == "resolved"]
    return resolved[-1] if resolved else snapshots[-1]


def _warnings(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    warnings = []
    for side, details in (("left", left), ("right", right)):
        for warning in details.get("warnings") or []:
            warnings.append(f"{side}: {warning}")
    return warnings[:20]
