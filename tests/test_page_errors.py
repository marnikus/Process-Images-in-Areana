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


@pytest.mark.unit
def test_match_arena_thread_error_with_trace_id():
    # Exact in-thread bubble text from the 12:36 run screenshot.
    line = ("Something went wrong while generating the response. "
            "Please try again. Trace ID: 5132d45a-77b6")
    hit = pe.match_page_error(line)
    assert hit.startswith("Page error: Something went wrong")
    assert "Trace ID: 5132d45a-77b6" in hit
    assert pe.match_page_error("Error Trace ID: abc-123") != ""
    assert pe.match_page_error(line, baseline=line) == ""  # stale: ignored


@pytest.mark.unit
def test_build_error_scan_js_collects_trace_id_bubbles():
    js = pe.build_error_scan_js()
    assert "trace id" in js  # in-thread bubbles have no alert role


@pytest.mark.unit
def test_match_second_arena_thread_error_sample():
    # Second real sample (12:56 run) — a different Trace ID, same signature.
    line = ("Something went wrong while generating the response. "
            "Please try again. Trace ID: 484e8c47-14e3")
    hit = pe.match_page_error(line)
    assert hit.startswith("Page error: Something went wrong")
    assert "Trace ID: 484e8c47-14e3" in hit


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_check_reraises_page_error_abort():
    """The wait loop fails FAST on page errors (no 180 s burn)."""
    from app.browser.output_wait import _poll_check

    async def boom():
        raise pe.PageErrorAbort("Page error: Something went wrong")

    with pytest.raises(pe.PageErrorAbort):
        await _poll_check(boom, 0.01)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_poll_check_contains_ordinary_errors():
    """Non-abort poll errors stay contained (retry next poll)."""
    from app.browser.output_wait import _poll_check

    async def boom():
        raise RuntimeError("cdp hiccup")

    diag, err = await _poll_check(boom, 0.01)
    assert diag is None and err == {"ready": False, "reason": "cdp hiccup"}
