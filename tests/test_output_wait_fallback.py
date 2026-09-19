"""Tests for C11 output_wait_fallback pure predicates."""
import pytest
from app.browser.output_wait_fallback import (
    should_fallback, is_mismatch_reason, _is_mismatch_block, _has_assoc_mismatch,
    _extract_fallback_src
)

def test_should_fallback_too_early():
    assert not should_fallback(5, {"allNew": 1})

def test_should_fallback_mismatch_block():
    diag = {"reason": "job_id_mismatch_no_matching_image", "allNew": 1}
    assert not should_fallback(20, diag)

def test_should_fallback_allnew_no_valid():
    diag = {"allNew": 1, "validBelow": 0, "validAbove": 0}
    assert should_fallback(20, diag)

def test_should_fallback_spinning_false_no_mismatch():
    diag = {"allNew": 1, "spinning": False}
    assert should_fallback(20, diag)

def test_is_mismatch_reason():
    assert is_mismatch_reason("job_id_mismatch_no_matching_image")
    assert is_mismatch_reason("job_id_mismatch")
    assert not is_mismatch_reason("timeout")

def test_is_mismatch_block():
    assert _is_mismatch_block({"reason": "job_id_mismatch_no_matching_image"})
    assert _is_mismatch_block({"mismatchDetails": [{}], "allNew": 1, "validBelow": 0, "validAbove": 0})
    assert not _is_mismatch_block({"allNew": 0})

def test_has_assoc_mismatch():
    assert _has_assoc_mismatch({"associatedJobId": "A", "expectedJobId": "B"})
    assert not _has_assoc_mismatch({"associatedJobId": "A", "expectedJobId": "A"})
    assert not _has_assoc_mismatch({})

def test_extract_fallback_src():
    assert _extract_fallback_src({"src": "http://x"}) == "http://x"
    assert _extract_fallback_src({"allNewDetails": [{"src": "http://y"}]}) == "http://y"
    assert _extract_fallback_src({}) is None
