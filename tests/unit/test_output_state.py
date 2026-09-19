"""Unit tests for output_state.flatten_diagnostics — the diag normaliser (B7).

RULE 8: fails if flattening inverts (non-dict rejected, defaults filled,
explicit keys preserved). Every consumer (output_wait, bridge) reads the
normalised shape.
"""

from __future__ import annotations

import pytest

from app.browser.output_state import flatten_diagnostics


@pytest.mark.unit
def test_non_dict_input_is_rejected_not_flattened():
    assert flatten_diagnostics("oops") == {"ready": False, "reason": "invalid_result"}
    assert flatten_diagnostics(None) == {"ready": False, "reason": "invalid_result"}
    assert flatten_diagnostics([1, 2]) == {"ready": False, "reason": "invalid_result"}


@pytest.mark.unit
def test_probe_result_gets_every_default_key():
    diag = flatten_diagnostics({"ready": True, "src": "https://r2/x.png"})
    assert diag["ready"] is True
    assert diag["src"] == "https://r2/x.png"
    for key, default in [
        ("jobFound", False), ("jobTop", None), ("prevJobTop", None), ("nextJobTop", None),
        ("jobIndex", -1), ("allJobs", 0), ("validAbove", 0), ("validBelow", 0),
        ("belowCount", 0), ("aboveCount", 0), ("allNew", 0), ("layoutReverse", False),
        ("orderCheck", ""), ("associatedJobId", None), ("expectedJobId", None),
        ("domPrevJobId", None), ("domNextJobId", None), ("visualPrevJobId", None),
        ("mismatchDetails", []), ("jobId", None),
    ]:
        assert diag[key] == default, key


@pytest.mark.unit
def test_explicit_values_are_preserved_not_overwritten():
    raw = {"ready": False, "jobTop": 421, "jobIndex": 2, "allNew": 3,
           "layoutReverse": True, "mismatchDetails": [{"src": "x"}]}
    diag = flatten_diagnostics(raw)
    assert diag["jobTop"] == 421
    assert diag["jobIndex"] == 2
    assert diag["allNew"] == 3
    assert diag["layoutReverse"] is True
    assert diag["mismatchDetails"] == [{"src": "x"}]


@pytest.mark.unit
def test_source_dict_not_mutated():
    raw = {"ready": True}
    flatten_diagnostics(raw)
    assert raw == {"ready": True}
