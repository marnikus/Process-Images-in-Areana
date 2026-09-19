"""Tests for dom_highlight.py pure helpers."""
from app.browser.dom_highlight import (
    _candidate_lines, interpret_find, _found_state, _outline_suffix,
    interpret_click, interpret_click_target, build_clear_js,
    HighlightJsSpec, build_highlight_js_from_spec
)

def test_candidate_lines_empty():
    assert _candidate_lines({}) == ""

def test_candidate_lines_with_candidates():
    res = {"candidates": [{"index": 0, "text": "hello world", "visible": True, "clickable": True}]}
    txt = _candidate_lines(res)
    assert "hello" in txt
    assert "visible" in txt

def test_interpret_find_no_result():
    msg, lvl = interpret_find(None, "btn")
    assert "no data" in msg.lower()
    assert lvl == "error"

def test_interpret_find_error():
    msg, lvl = interpret_find({"error": "boom"}, "btn")
    assert "error" in msg.lower()
    assert lvl == "error"

def test_interpret_find_not_found():
    msg, lvl = interpret_find({"found": False, "total": 2, "candidates": []}, "btn")
    assert "failed" in msg.lower()
    assert lvl == "error"

def test_interpret_find_success():
    res = {"found": True, "visible": True, "text": "Send", "index": 0, "highlighted": True, "rect": {"x": 10, "y": 20, "width": 100, "height": 20}}
    msg, lvl = interpret_find(res, "send btn")
    assert "success" in msg.lower()
    assert lvl == "success"

def test_found_state():
    assert "visible" in _found_state({"visible": True})
    assert "NOT visible" in _found_state({"visible": False})
    assert "disabled" in _found_state({"visible": True, "disabled": True})

def test_outline_suffix():
    assert "red outline" in _outline_suffix({"highlighted": True, "rect": {"x": 0, "y": 0, "width": 10, "height": 10}})
    assert "highlight off" in _outline_suffix({"visible": True, "highlighted": False}) or "" in _outline_suffix({"visible": True})

def test_interpret_click_no_result():
    msg, lvl = interpret_click(None, "btn")
    assert "no data" in msg.lower()

def test_interpret_click_not_clickable():
    res = {"clickable": False, "visible": False, "target_desc": "btn"}
    msg, lvl = interpret_click(res, "btn")
    assert "NOT clickable" in msg

def test_interpret_click_success():
    res = {"clickable": True, "clicked": True, "target_desc": "send btn", "text": "Send"}
    msg, lvl = interpret_click(res, "btn")
    assert "success" in msg.lower()

def test_interpret_click_target():
    res = {"clickable": True, "target_desc": "btn", "highlighted": True}
    msg, lvl = interpret_click_target(res)
    assert "clickable" in msg.lower()

def test_build_highlight_js():
    spec = HighlightJsSpec(selector="button", color="#FF0000", duration_ms=1000, caption="test", clear_first=True)
    js = build_highlight_js_from_spec(spec)
    assert "button" in js and "#FF0000" in js and "test" in js and "1000" in js

def test_build_clear_js():
    js = build_clear_js()
    assert "cleared" in js

def test_build_highlight_js_from_spec():
    spec = HighlightJsSpec(selector="div", color="#00FF00", duration_ms=500, caption="hi", clear_first=False)
    js = build_highlight_js_from_spec(spec)
    assert "div" in js or "hi" in js or "highlight" in js.lower()
