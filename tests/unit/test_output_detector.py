"""Unit tests for output_detector.py — pure decision logic, <1ms (Phase 2).

RULE 18: file 60-200 LOC ideal.
RULE 16: func LOC ≤30, CC ≤10.
"""

import pytest

from app.browser.output_detector import (
    decide_ready,
    detect_new_output,
    is_job_id_match,
    is_mismatch_reason,
    is_ready_result,
    should_download,
    should_fallback_pure,
)


@pytest.mark.unit
def test_is_job_id_match_pure():
    assert is_job_id_match("ABC", "ABC") is True
    assert is_job_id_match("ABC", "XYZ") is False
    assert is_job_id_match(None, "ABC") is False
    assert is_job_id_match("ABC", None) is True  # no expectation → allow
    assert is_job_id_match(None, None) is True


@pytest.mark.unit
def test_should_download_pure():
    ok, _ = should_download({"ready": True, "src": "https://a.com/img.png", "associatedJobId": "J1", "expectedJobId": "J1"})
    assert ok is True
    ok, reason = should_download({"ready": True, "src": "https://a.com/img.png", "associatedJobId": "J1", "expectedJobId": "J2"})
    assert ok is False
    assert "mismatch" in reason
    ok, _ = should_download({"ready": False, "reason": "generating"})
    assert ok is False


@pytest.mark.unit
def test_should_fallback_pure():
    assert should_fallback_pure(5, {"allNew": 1}) is False  # <10s no fallback
    assert should_fallback_pure(15, {"allNew": 1, "validBelow": 0, "validAbove": 0}) is True
    assert should_fallback_pure(15, {"reason": "job_id_mismatch_no_matching_image", "allNew": 1}) is False
    assert should_fallback_pure(15, {"allNew": 1, "validBelow": 0, "validAbove": 0, "mismatchDetails": [{"a": 1}]}) is False


@pytest.mark.unit
def test_detect_new_output_pure():
    baseline = ["https://a.com/old1.png", "https://a.com/old2.png"]
    current = ["https://a.com/old1.png", "https://a.com/old2.png", "https://a.com/new.png"]
    new = detect_new_output(baseline, current)
    assert new == ["https://a.com/new.png"]
    assert detect_new_output([], ["a", "b"]) == ["a", "b"]
    assert detect_new_output(["a"], ["a"]) == []


@pytest.mark.unit
def test_decide_ready_pure():
    diag_ready = {"ready": True, "src": "https://a.com/img.png", "associatedJobId": "J1", "expectedJobId": "J1"}
    res = decide_ready(diag_ready, elapsed=1)
    assert res["action"] == "download"

    diag_mismatch = {"ready": True, "src": "https://a.com/img.png", "associatedJobId": "J1", "expectedJobId": "J2"}
    res = decide_ready(diag_mismatch, elapsed=1)
    assert res["action"] == "error"

    diag_spin = {"ready": False, "spinning": True, "reason": "generating_spinner_visible"}
    res = decide_ready(diag_spin, elapsed=1)
    assert res["action"] == "wait"

    diag_cancel = {"reason": "cancelled"}
    res = decide_ready(diag_cancel, elapsed=1)
    assert res["action"] == "cancelled"


@pytest.mark.unit
def test_is_ready_and_mismatch_pure():
    assert is_ready_result({"ready": True}) is True
    assert is_ready_result({"ready": False}) is False
    assert is_mismatch_reason("job_id_mismatch") is True
    assert is_mismatch_reason("generating") is False
