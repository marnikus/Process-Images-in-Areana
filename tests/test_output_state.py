"""Tests for output_state pure helpers — real logic, no mocks."""

from app.browser.output_state import (
    describe_order,
    is_large_candidate,
    is_loading_reason,
    is_order_wait_reason,
    is_reference_candidate,
    is_terminal_ready,
    normalize_old_keys,
    normalize_src_key,
    select_best_fallback,
    should_accept_fallback,
)


def test_normalize_strips_query_for_rotation():
    base = "https://m.r2.cloudflarestorage.com/k/1789508403662-02-c.jpeg"
    a = base + "?X-Amz-1"
    b = base + "?X-Amz-2"
    assert normalize_src_key(a) == normalize_src_key(b)
    assert "02-c.jpeg" in normalize_src_key(a)


def test_normalize_empty_vs_broken():
    assert normalize_src_key("") == ""
    assert normalize_src_key(None) == ""
    assert normalize_old_keys(None) == set()
    assert normalize_old_keys([]) == set()


def test_normalize_old_keys_dedupes_rotation():
    base = "https://m.r2.cloudflarestorage.com/k/img.png"
    keys = normalize_old_keys([base + "?a=1", base + "?a=2"])
    assert len(keys) == 1


def test_is_large_by_width():
    assert is_large_candidate({"width": 500, "rect": {"width": 500}}) is True
    assert is_large_candidate({"width": 10, "rect": {"width": 10}}) is False


def test_is_large_by_50vh_class():
    cand = {"width": 10, "rect": {"width": 10}, "cls": "h-[50vh] w-[50vh]"}
    assert is_large_candidate(cand) is True


def test_is_large_by_cover_with_display():
    cand = {"width": 0, "rect": {"width": 120}, "cls": "object-cover"}
    assert is_large_candidate(cand) is True
    small = {"width": 0, "rect": {"width": 50}, "cls": "object-cover"}
    assert is_large_candidate(small) is False


def test_is_reference_needs_inside_job():
    cand = {"insideJob": False, "rect": {"width": 100}, "cls": "w-32"}
    assert is_reference_candidate(cand) is False


def test_is_reference_small_inside():
    cand = {"insideJob": True, "rect": {"width": 128}, "cls": "w-32"}
    assert is_reference_candidate(cand) is True
    large = {"insideJob": True, "rect": {"width": 400}, "cls": "big"}
    assert is_reference_candidate(large) is False


def test_select_best_fallback_prefers_large():
    details = [
        {"src": "small", "width": 100, "top": 900, "isLarge": False},
        {"src": "large", "width": 800, "top": 100, "isLarge": True},
    ]
    best = select_best_fallback(details)
    assert best["src"] == "large"


def test_select_best_fallback_empty_vs_broken():
    assert select_best_fallback([]) is None
    assert select_best_fallback(None) is None


def test_should_accept_fallback_needs_stable():
    assert should_accept_fallback(True, 5, 20.0) is False
    assert should_accept_fallback(False, 2, 20.0) is False
    assert should_accept_fallback(False, 3, 5.0) is False
    assert should_accept_fallback(False, 3, 10.0) is True


def test_is_terminal_ready():
    assert is_terminal_ready({"ready": True, "src": "http://x/y.png"}) is True
    assert is_terminal_ready({"ready": True, "src": ""}) is False
    assert is_terminal_ready({"ready": False, "src": "x"}) is False


def test_loading_and_order_reasons():
    assert is_loading_reason("not_complete") is True
    assert is_loading_reason("no_new") is False
    assert is_order_wait_reason("no_new") is True
    assert is_order_wait_reason("ready") is False


def test_describe_order_contains_fields():
    result = {
        "reason": "no_new",
        "jobFound": True,
        "jobTop": 800,
        "prevJobTop": 400,
        "validAbove": 0,
        "invalidAbove": 1,
        "allNew": 2,
        "orderCheck": "x" * 200,
    }
    text = describe_order(result)
    assert "no_new" in text
    assert "jobFound=True" in text
    assert "valid=0" in text
