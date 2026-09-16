"""Unit tests — auto-connect page detection (spec 02: pattern filter, unique page id).

RULE 8: real functions, real data shapes (Chrome /json/list entries).
"""

from __future__ import annotations

import pytest

from app.browser.autoconnect_match import (
    compile_patterns,
    normalize_url,
    page_id,
    page_id_from_ws,
    select_pages,
    split_patterns,
    url_matches,
)


def tab(pid: str, url: str, title: str = "Arena", host: str = "127.0.0.1", port: int = 9223) -> dict:
    return {
        "id": pid,
        "title": title,
        "url": url,
        "ws_url": f"ws://{host}:{port}/devtools/page/{pid}",
        "type": "page",
    }


ARENA_TABS = [
    tab("AAA", "https://arena.ai/c/one"),
    tab("BBB", "https://arena.ai/c/two"),
    tab("CCC", "https://docs.python.org/3/"),
]


@pytest.mark.unit
def test_normalize_url_drops_scheme_fragment_and_slash():
    assert normalize_url("HTTPS://Arena.AI/c/1/#frag") == "arena.ai/c/1"
    assert normalize_url("  arena.ai/  ") == "arena.ai"
    assert normalize_url("") == ""


@pytest.mark.unit
def test_split_patterns_accepts_comma_semicolon_newline():
    assert split_patterns("arena.ai, lmarena.ai;chat\n*.ai") == ["arena.ai", "lmarena.ai", "chat", "*.ai"]
    assert split_patterns("   ") == []


@pytest.mark.unit
def test_compile_patterns_normalizes_and_dedupes():
    assert compile_patterns("https://Arena.ai/, arena.ai | lmarena.ai") == ["arena.ai", "lmarena.ai"]
    assert compile_patterns("") == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "url,pattern,expected",
    [
        ("https://arena.ai/c/1", "arena.ai", True),
        ("https://lmarena.ai/chat", "arena.ai", True),
        ("https://docs.python.org/3/", "arena.ai", False),
        ("https://arena.ai/c/1", "*.ai/c/*", True),
        ("https://arena.ai/c/1", "", False),
        ("", "arena.ai", False),
    ],
)
def test_url_matches_substring_and_wildcard(url, pattern, expected):
    assert url_matches(url, compile_patterns(pattern)) is expected


@pytest.mark.unit
def test_title_can_satisfy_pattern_when_url_is_generic():
    # A freshly opened tab may still show a bare URL — the title keeps it discoverable
    assert url_matches("https://new-tab.page/", ["arena"], title="Arena — Benchmark the Best AI Models") is True
    assert url_matches("https://new-tab.page/", ["arena"], title="Google") is False


@pytest.mark.unit
def test_page_id_prefers_id_then_ws_url():
    assert page_id(tab("AAA", "https://arena.ai")) == "AAA"
    assert page_id({"ws_url": "ws://127.0.0.1:9223/devtools/page/XYZ"}) == "XYZ"
    assert page_id_from_ws("ws://127.0.0.1:9223/devtools/page/XYZ") == "XYZ"
    assert page_id({}) == ""


@pytest.mark.unit
def test_duplicate_urls_are_two_pages_because_ids_differ():
    tabs = [tab("AAA", "https://arena.ai/c/same"), tab("BBB", "https://arena.ai/c/same")]
    sel = select_pages(tabs, compile_patterns("arena.ai"))
    assert sel.matched == 2
    assert [p["page_id"] for p in sel.pages] == ["AAA", "BBB"]
    assert sel.duplicates == 0


@pytest.mark.unit
def test_repeated_page_id_is_collapsed_once():
    tabs = [tab("AAA", "https://arena.ai/c/1"), tab("AAA", "https://arena.ai/c/1", host="localhost")]
    sel = select_pages(tabs, compile_patterns("arena.ai"))
    assert sel.matched == 1
    assert sel.duplicates == 1
    assert sel.pages[0]["ws_url"].startswith("ws://127.0.0.1")


@pytest.mark.unit
def test_devtools_and_internal_pages_never_match():
    tabs = ARENA_TABS + [
        tab("DDD", "devtools://devtools/bundled/inspector.html", title="DevTools"),
        tab("EEE", "chrome://newtab/"),
        tab("FFF", "about:blank"),
    ]
    sel = select_pages(tabs, compile_patterns("*"))  # wildcard would match every real page
    ids = {p["page_id"] for p in sel.pages}
    assert ids == {"AAA", "BBB", "CCC"}
    assert sel.skipped_internal == 3


@pytest.mark.unit
def test_non_matching_urls_are_skipped_and_counted():
    sel = select_pages(ARENA_TABS, compile_patterns("arena.ai"))
    assert sel.scanned == 3
    assert sel.matched == 2
    assert sel.skipped_pattern == 1
    assert sel.error == ""


@pytest.mark.unit
def test_max_pages_limits_and_flags():
    sel = select_pages(ARENA_TABS, compile_patterns("arena.ai"), max_pages=1)
    assert len(sel.pages) == 1
    assert sel.limited is True
    assert sel.matched == 2  # detection still reports what it saw


@pytest.mark.unit
def test_empty_scan_is_not_an_error():
    sel = select_pages([], compile_patterns("arena.ai"))
    assert sel.pages == []
    assert sel.scanned == 0
    assert sel.error == ""


@pytest.mark.unit
def test_selection_accepts_tabinfo_objects():
    from app.browser.cdp_client import TabInfo

    tabs = [TabInfo(id="AAA", title="Arena", url="https://arena.ai/c/1", ws_url="ws://127.0.0.1:9223/devtools/page/AAA")]
    sel = select_pages(tabs, compile_patterns("arena.ai"))
    assert sel.matched == 1
    assert sel.pages[0]["page_id"] == "AAA"
