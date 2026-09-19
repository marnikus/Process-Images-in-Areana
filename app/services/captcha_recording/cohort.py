"""D3/F-C: pure cohort statistics over recording summaries.

Actor label (who solved: bot|manual|mixed) is independent of result label
(passed|failed). Pure success-rate stats only count rows whose result_label is
a definite outcome (passed|failed); unknown rows are reported separately and
never folded into the rate. The vocabularies come from `models` — one source,
so a new label can never silently count as "unknown".
"""

from __future__ import annotations

from typing import Any

from .models import VALID_ACTOR_LABELS, VALID_RESULT_LABELS

DEFINITE_RESULTS = frozenset({"passed", "failed"})
_ACTOR_KEYS = tuple(sorted(VALID_ACTOR_LABELS))
_RESULT_KEYS = tuple(sorted(VALID_RESULT_LABELS))


def _label(row: dict[str, Any], key: str) -> str:
    value = str(row.get(key) or "unknown")
    return value if value in VALID_ACTOR_LABELS else "unknown"


def _result(row: dict[str, Any]) -> str:
    value = str(row.get("result_label") or "unknown")
    return value if value in VALID_RESULT_LABELS else "unknown"


def _tally(sessions):
    """Actor x result matrix plus per-result totals."""
    matrix: dict[str, dict[str, int]] = {}
    totals = {key: 0 for key in _RESULT_KEYS}
    for row in sessions or []:
        actor, result = _label(row, "actor_label"), _result(row)
        row_counts = matrix.setdefault(actor, {key: 0 for key in _RESULT_KEYS})
        row_counts[result] += 1
        totals[result] += 1
    return matrix, totals


def cohort(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """Actor x result matrix plus a pure success rate over definite rows only."""
    matrix, totals = _tally(sessions)
    for actor in _ACTOR_KEYS:  # stable keys even with no rows
        matrix.setdefault(actor, {key: 0 for key in _RESULT_KEYS})
    passed, failed = totals["passed"], totals["failed"]
    definite = passed + failed
    return {
        "total": len(sessions or []),
        "definite": definite,
        "passed": passed,
        "failed": failed,
        "unknown": totals["unknown"],
        # rate over definite rows only (None when no definite evidence)
        "success_rate": (passed / definite) if definite else None,
        "matrix": matrix,
    }
