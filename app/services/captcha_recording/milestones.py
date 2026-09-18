"""Closed milestone vocabulary shared by the automatic and manual solve paths.

Pure module (no I/O, no browser, no Qt): it turns the bounded, token-free
evidence already produced by one captcha encounter into the named edge list a
recording needs, so a human-cleared and a provider-cleared session can be
aligned phase by phase instead of compared as raw event soup.

Offsets are session-relative milliseconds. Derived rows are anchored on the
`detected` stamp (`base_ms`) and on the solve timing already present in the
report, so both paths stay directly comparable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

PHASES: Tuple[str, ...] = (
    "detected", "task_created", "token_ready", "pre_injection", "field_delivery",
    "manual_field_filled", "continue_clicked", "dialog_cleared",
    "acceptance_candidate", "page_error", "token_stale", "not_accepted",
    "auto_failed", "stopped", "interrupted", "session_end", "job_result",
)

#: Phases only the live path can stamp (page probes / the job join).
LIVE_ONLY = frozenset({"detected", "manual_field_filled", "dialog_cleared", "job_result"})

#: Phases that legitimately exist only in a provider-solved session.
PROVIDER_PHASES = frozenset({"task_created", "token_ready", "pre_injection",
                             "field_delivery", "continue_clicked", "token_stale",
                             "not_accepted", "auto_failed"})

_ACCEPTANCE = {
    "solved": "accepted_candidate",
    "manual": "accepted_candidate",
    "page_error": "page_error",
    "token_stale": "stale",
    "auto_failed": "not_accepted",
    "stopped": "none",
    "interrupted": "none",
    "none": "none",
}

_STATUS_PHASES = {
    "auto_failed": "auto_failed",
    "token_stale": "token_stale",
    "stopped": "stopped",
    "interrupted": "interrupted",
}


def acceptance_state(outcome: Any) -> str:
    """Observed verdict at the solve edge (never a claim of server acceptance)."""
    known = str(_get(outcome, "acceptance_state", "") or "")
    return known or _ACCEPTANCE.get(str(_get(outcome, "status", "")), "none")


def verifier_for(outcome: Any) -> str:
    """Which evidence backed the candidate: callback plus closure, or closure."""
    known = str(_get(outcome, "verifier", "") or "")
    if known:
        return known
    return "callback+closure" if "cb=called" in str(_get(outcome, "inject", "") or "") else "closure"


def live_phases(live: Sequence[Mapping[str, Any]]) -> set:
    """Phases already stamped from the live path (they win over derivation)."""
    return {str(row.get("phase", "")) for row in live or ()}


def derive(outcome: Any, report: Optional[Mapping[str, Any]], live: Sequence[Mapping[str, Any]],
           base_ms: int = 0) -> List[Dict[str, Any]]:
    """Named edges for the phases no live stamp covered, in vocabulary order."""
    seen = live_phases(live)
    rows = [row for row in _candidates(outcome, report or {}, base_ms)
            if row["phase"] not in seen and row["phase"] in PHASES]
    order = {phase: index for index, phase in enumerate(PHASES)}
    return sorted(rows, key=lambda row: (row["offset_ms"], order.get(row["phase"], 99)))


def _candidates(outcome: Any, report: Mapping[str, Any],
                base_ms: int) -> List[Dict[str, Any]]:
    status = str(_get(outcome, "status", "") or "")
    method = str(_get(outcome, "method", "") or "") or str(report.get("method", ""))
    rows: List[Dict[str, Any]] = []
    if method == "auto":
        rows.extend(_auto_rows(outcome, report, base_ms))
    if status in ("solved", "manual"):
        rows.append(_row("acceptance_candidate", _offset(base_ms, _edge_seconds(outcome, report)),
                         {"state": acceptance_state(outcome), "verifier": verifier_for(outcome)}))
    if status in _STATUS_PHASES:
        rows.append(_row(_STATUS_PHASES[status], _offset(base_ms, _edge_seconds(outcome, report)),
                         {"status": status, "reason": _bounded(_get(outcome, "reason", ""))}))
    error = report.get("page_error") or {}
    if isinstance(error, Mapping) and error.get("text"):
        rows.append(_row("page_error", _offset(base_ms, error.get("at_s")),
                         {"text": _bounded(error.get("text")), "status": status}))
    return rows


def _auto_rows(outcome: Any, report: Mapping[str, Any], base_ms: int) -> List[Dict[str, Any]]:
    """Provider edges; the token edge anchors every later step of the attempt."""
    t0 = _seconds(report.get("detect_to_solve_s"), 0.0)
    token = _token_seconds(outcome, report)
    at = base_ms + int(round(t0 * 1000))
    token_at = base_ms + int(round((t0 + token) * 1000))
    return [
        _row("task_created", at, _task_data(outcome, report)),
        _row("token_ready", token_at, _token_data(outcome, report)),
        _row("pre_injection", token_at, _mapping(report.get("preinject"))),
        _row("field_delivery", token_at, _mapping(report.get("postinject"))),
        _row("continue_clicked", token_at, _mapping(report.get("continue"))),
    ]


def _task_data(outcome: Any, report: Mapping[str, Any]) -> Dict[str, Any]:
    return {"task_type": str(report.get("task_type", "")),
            "is_invisible": bool(report.get("invisible")),
            "website_host": _host(str(report.get("url", ""))),
            "sitekey_source": str(report.get("sitekey_source", "none")),
            "task_id_present": bool(_get(outcome, "task_id", ""))}


def _token_data(outcome: Any, report: Mapping[str, Any]) -> Dict[str, Any]:
    token = report.get("token") or {}
    return {"polls": int(report.get("polls") or _get(outcome, "polls", 0) or 0),
            "token_sec": round(_token_seconds(outcome, report), 1),
            "token_len": int((report.get("postinject") or {}).get("len") or 0),
            "challenge_identity": str(report.get("challenge_identity", ""))[:120],
            "page_identity": str(report.get("page_identity", ""))[:120],
            "stale": bool(report.get("stale")) or isinstance(token, Mapping) is False}


def _edge_seconds(outcome: Any, report: Mapping[str, Any]) -> Optional[float]:
    """Seconds from detection to the deciding edge, same clock as the report."""
    if report.get("acceptance"):
        return (report.get("detect_to_solve_s") or 0) + _token_seconds(outcome, report)
    return None


def _token_seconds(outcome: Any, report: Mapping[str, Any]) -> float:
    token = report.get("token") or {}
    if isinstance(token, Mapping) and token.get("at_s") is not None:
        return max(0.0, _seconds(token.get("at_s"), 0.0) - _seconds(report.get("detect_to_solve_s"), 0.0))
    return _seconds(_get(outcome, "token_sec", 0), 0.0)


def _row(phase: str, offset_ms: int, data: Mapping[str, Any]) -> Dict[str, Any]:
    return {"phase": phase, "offset_ms": int(offset_ms), "data": dict(data or {})}


def _mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _clip(item) for key, item in value.items()}
    if value is None:
        return {}
    return {"summary": _bounded(value)}


def _clip(value: Any) -> Any:
    if isinstance(value, (str, bytes)):
        return _bounded(value)
    if isinstance(value, Mapping):
        return _mapping(value)
    if isinstance(value, (list, tuple)):
        return [_clip(item) for item in list(value)[:8]]
    return value


def _bounded(value: Any, limit: int = 400) -> str:
    return str(value or "")[:limit]


def _host(url: str) -> str:
    try:
        from urllib.parse import urlsplit
        return urlsplit(url).hostname or ""
    except Exception:
        return ""


def _offset(base_ms: int, seconds: Optional[float]) -> int:
    if seconds is None:
        return int(base_ms)
    return int(base_ms) + int(round(max(0.0, seconds) * 1000))


def _seconds(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get(source: Any, key: str, default: Any = "") -> Any:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)
