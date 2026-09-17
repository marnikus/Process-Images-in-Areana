"""Tests for app/utils/page_errors.py — page-error fast-fail matching."""

import pytest

from app.utils import page_errors as pe


@pytest.mark.unit
def test_match_limit_variants():
    assert pe.match_page_error("You have reached your daily limit") != ""
    assert pe.match_page_error("Rate limit exceeded, try again in 5") != ""
    assert pe.match_page_error("Quota exceeded for this model") != ""
    assert pe.match_page_error("Limit Reached") != ""


@pytest.mark.unit
def test_match_failure_variants():
    assert pe.match_page_error("Something went wrong") != ""
    assert pe.match_page_error("Failed to generate image") != ""
    assert pe.match_page_error("Generation failed, please retry") != ""
    assert pe.match_page_error("Service unavailable") != ""


@pytest.mark.unit
def test_match_clean_text_empty():
    assert pe.match_page_error("") == ""
    assert pe.match_page_error("Generating your image...") == ""
    assert pe.match_page_error("Try again") == ""  # bare button, no signal
    assert pe.match_page_error(None) == ""
    assert pe.match_page_error(123) == ""


@pytest.mark.unit
def test_match_ignores_stale_baseline():
    stale = "Rate limit exceeded"
    assert pe.match_page_error(stale, baseline=stale) == ""
    fresh = stale + "\nQuota exceeded for this model"
    hit = pe.match_page_error(fresh, baseline=stale)
    assert hit.startswith("Page error: Quota")


@pytest.mark.unit
def test_match_truncates_long_line():
    long_line = "Something went wrong " + "x" * 500
    hit = pe.match_page_error(long_line)
    assert hit.startswith("Page error: Something")
    assert len(hit) <= len("Page error: ") + pe.MAX_LINE


@pytest.mark.unit
def test_build_error_scan_js_scopes_alerts():
    js = pe.build_error_scan_js()
    assert 'role="alert"' in js
    assert "toast" in js
    assert "innerText" in js
