"""Unit tests for cdp_protocol.py — pure logic, no I/O, <1ms each (Phase 2).

RULE 18: file 60-200 LOC ideal, current ~120 LOC.
RULE 16: func LOC ≤30, CC ≤10.
"""

import pytest

from app.browser.cdp_protocol import (
    TabInfo,
    deduplicate_tabs_by_id,
    filter_real_tabs,
    is_devtools_url,
    normalize_ws_url,
    parse_tabs,
)


@pytest.mark.unit
def test_is_devtools_url_pure():
    assert is_devtools_url("") is True
    assert is_devtools_url("devtools://foo") is True
    assert is_devtools_url("chrome://settings") is True
    assert is_devtools_url("https://arena.ai") is False
    assert is_devtools_url("https://arena.ai", title="DevTools") is True


@pytest.mark.unit
def test_normalize_ws_url_pure():
    ws = "ws://127.0.0.1:9222/devtools/page/ABC"
    norm = normalize_ws_url(ws, "localhost", 9223)
    assert norm == "ws://localhost:9223/devtools/page/ABC"
    assert normalize_ws_url("", "127.0.0.1", 9222) == ""


@pytest.mark.unit
def test_parse_tabs_pure():
    items = [
        {"id": "1", "title": "Arena", "url": "https://arena.ai", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1", "type": "page"},
        {"id": "2", "title": "DevTools", "url": "devtools://devtools/bundled", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/2", "type": "page"},
        {"id": "3", "title": "Other", "url": "https://example.com", "type": "other"},  # filtered by type
    ]
    tabs = parse_tabs(items, preferred_host="127.0.0.1", preferred_port=9222, include_devtools=True)
    assert len(tabs) == 2  # page type only
    tabs_no_dev = parse_tabs(items, include_devtools=False)
    assert len(tabs_no_dev) == 1
    assert tabs_no_dev[0].id == "1"


@pytest.mark.unit
def test_filter_real_tabs_pure():
    tabs = [
        TabInfo(id="1", title="Arena", url="https://arena.ai", ws_url="ws://1"),
        TabInfo(id="2", title="DevTools", url="devtools://foo", ws_url="ws://2"),
    ]
    real = filter_real_tabs(tabs)
    assert len(real) == 1
    assert real[0].id == "1"


@pytest.mark.unit
def test_deduplicate_tabs_by_id_pure():
    tabs = [
        TabInfo(id="A", title="T1", url="https://a.com", ws_url="ws://127.0.0.1:9222/devtools/page/A"),
        TabInfo(id="A", title="T1 dup", url="https://a.com", ws_url="ws://localhost:9222/devtools/page/A"),
        TabInfo(id="B", title="T2", url="https://b.com", ws_url="ws://127.0.0.1:9222/devtools/page/B"),
    ]
    dedup = deduplicate_tabs_by_id(tabs, preferred_host="127.0.0.1")
    assert len(dedup) == 2
    ids = {t.id for t in dedup}
    assert ids == {"A", "B"}


@pytest.mark.unit
def test_parse_tabs_empty():
    assert parse_tabs([]) == []
    assert parse_tabs(None) == []  # type: ignore
    assert parse_tabs([{"not": "dict"}]) == []  # no url
