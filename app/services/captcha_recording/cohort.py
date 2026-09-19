"""D3/F-C: pure cohort statistics over recording summaries.

Actor label (who solved: bot|manual) is independent of result label
(passed|failed|mixed). Pure success-rate stats only count rows whose
result_label is a definite outcome (passed|failed); unknown/mixed rows are
reported separately, never folded into the rate.
"""

from __future__ import annotations

from typing import Any

DEFINITE_RESULTS = frozenset({"passed", "failed"})


def _label(row: dict[str, Any], key: str) -> str:
    value = str(row.get(key) or "unknown")
    return value if value in ("unknown", "bot", "manual") else "unknown"


def _result(row: dict[str, Any]) -> str:
    value = str(row.get("result_label") or "unknown")
    return value if value in ("unknown", "passed", "failed", "mixed") else "unknown"


def _tally(sessions):
    """Actor x result matrix plus totals over all rows."""
    matrix: dict[str, dict[str, int]] = {}
    passed = failed = mixed = unknown = 0
    for row in sessions or []:
        actor, result = _label(row, "actor_label"), _result(row)
        row_counts = matrix.setdefault(actor, {"passed": 0, "failed": 0, "mixed": 0, "unknown": 0})
        row_counts[result] += 1
        if result == "passed":
            passed += 1
        elif result == "failed":
            failed += 1
        elif result == "mixed":
            mixed += 1
        else:
            unknown += 1
    return matrix, passed, failed, mixed, unknown


def cohort(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Actor x result matrix plus a pure success rate over definite rows only."""
    matrix, passed, failed, mixed, unknown = _tally(sessions)
    for actor in ("bot", "manual"):  # guarantee stable keys even with no rows
        actor_counts = matrix.setdefault(actor, {})
        for result in ("passed", "failed", "mixed", "unknown"):
            actor_counts.setdefault(result, 0)
    definite = passed + failed
    return {
        "total": len(sessions or []),
        "definite": definite,
        "passed": passed,
        "failed": failed,
        "mixed": mixed,
        "unknown": unknown,
        # rate over definite rows only (None when no definite evidence)
        "success_rate": (passed / definite) if definite else None,
        "matrix": matrix,
    }
